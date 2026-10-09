"""Functional-programming discipline, checked instead of merely written down.

    python -m tools.check_fp          # the whole repo; exit 1 on any finding

Four rules, each about a defect class an AI agent (or anyone) writes fluently:

  mutable-constant    A module-level UPPER_CASE name bound to a list, dict or
                      set. Anything that imports it can change it for every
                      other caller. Use a tuple, frozenset or MappingProxyType.
  mutated-argument    In a pure module, a function that changes its caller's
                      data: item or attribute assignment, `del`, or a mutating
                      method call on a parameter. Return a new value instead.
  impure-core         In a pure module, any I/O: importing the database,
                      web or OS layers, `async def`, or `global`. Pure modules
                      decide; app/services.py (the imperative shell) acts.
  mock-in-unit-test   A unit test that imports unittest.mock or takes the
                      monkeypatch / mocker fixture. Unit tests exercise pure
                      code with plain values; mocks belong in integration
                      tests, where a collaborator is real but inconvenient.

Limits: impure-core judges direct imports only (app.models imports SQLAlchemy,
so rules.py reaches it transitively for the Status enum). mutated-argument
follows names, not aliases: `ys = xs; ys.append(1)` is not caught.
"""

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ("app", "scripts", "tools", "tests", "alembic", ".claude/hooks")
PURE_MODULES = frozenset({"app/rules.py", "app/schema_compare.py"})

CONSTANT = re.compile(r"^[A-Z][A-Z0-9_]*$")
MUTABLE_LITERALS = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
MUTABLE_CONSTRUCTORS = frozenset({"list", "dict", "set", "defaultdict", "Counter", "OrderedDict", "deque"})
MUTATORS = frozenset({
    "append", "extend", "insert", "pop", "remove", "clear", "update", "add",
    "discard", "setdefault", "sort", "reverse", "popitem",
})
IMPURE_IMPORTS = frozenset({
    "sqlalchemy", "fastapi", "starlette", "subprocess", "os", "shutil", "socket",
    "httpx", "requests", "aiomysql", "aiosqlite", "asyncio", "random",
})
MOCK_FIXTURES = frozenset({"monkeypatch", "mocker"})


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.rule}  {self.message}"


def _is_mutable(value: ast.expr) -> bool:
    if isinstance(value, MUTABLE_LITERALS):
        return True
    return (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and value.func.id in MUTABLE_CONSTRUCTORS)


def _mutable_constants(tree: ast.Module, path: str) -> list[Finding]:
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.value is not None:
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for t in targets:
            if isinstance(t, ast.Name) and CONSTANT.match(t.id) and _is_mutable(value):
                out.append(Finding(path, node.lineno, "mutable-constant",
                                   f"{t.id} is a mutable container; use a tuple, frozenset or MappingProxyType"))
    return out


def _root(node: ast.expr) -> str | None:
    """The name at the bottom of `a.b[c].d`, or None."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    a = fn.args
    names = [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)]
    names += [p.arg for p in (a.vararg, a.kwarg) if p is not None]
    return frozenset(n for n in names if n not in ("self", "cls"))


def _mutated_arguments(tree: ast.Module, path: str) -> list[Finding]:
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = _params(fn)
        for node in ast.walk(fn):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            elif isinstance(node, ast.Delete):
                targets = node.targets
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr in MUTATORS):
                targets = [node.func.value] if _root(node.func.value) in params else []
                if targets:
                    out.append(Finding(path, node.lineno, "mutated-argument",
                                       f"{fn.name}() calls .{node.func.attr}() on its argument "
                                       f"{_root(node.func.value)}"))
                continue
            for t in targets:
                if isinstance(t, (ast.Subscript, ast.Attribute)) and _root(t) in params:
                    out.append(Finding(path, t.lineno, "mutated-argument",
                                       f"{fn.name}() changes its argument {_root(t)}"))
    return out


def _impure_core(tree: ast.Module, path: str) -> list[Finding]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):  # every node judged below is a statement
            continue
        why = None
        if isinstance(node, ast.Import):
            bad = [a.name for a in node.names if a.name.split(".")[0] in IMPURE_IMPORTS]
            why = f"imports {', '.join(bad)}" if bad else None
        elif isinstance(node, ast.ImportFrom) and node.module:
            why = f"imports {node.module}" if node.module.split(".")[0] in IMPURE_IMPORTS else None
        elif isinstance(node, ast.AsyncFunctionDef):
            why = f"{node.name}() is async"
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            why = f"declares {type(node).__name__.lower()} {', '.join(node.names)}"
        if why:
            out.append(Finding(path, node.lineno, "impure-core", f"a pure module {why}"))
    return out


def _mocks_in_unit_test(tree: ast.Module, path: str) -> list[Finding]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.startswith("unittest.mock") for a in node.names):
            out.append(Finding(path, node.lineno, "mock-in-unit-test", "imports unittest.mock"))
        elif isinstance(node, ast.ImportFrom) and (
            node.module == "unittest.mock"
            or (node.module == "unittest" and any(a.name == "mock" for a in node.names))
        ):
            out.append(Finding(path, node.lineno, "mock-in-unit-test", "imports unittest.mock"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for name in sorted(_params(node) & MOCK_FIXTURES):
                out.append(Finding(path, node.lineno, "mock-in-unit-test",
                                   f"{node.name}() takes the {name} fixture"))
    return out


def check_source(src: str, path: str, pure: bool | None = None) -> list[Finding]:
    tree = ast.parse(src, filename=path)
    pure = path in PURE_MODULES if pure is None else pure
    findings = _mutable_constants(tree, path)
    if pure:
        findings += _mutated_arguments(tree, path) + _impure_core(tree, path)
    if path.startswith("tests/unit/"):
        findings += _mocks_in_unit_test(tree, path)
    return findings


def check_tree(root: Path = ROOT) -> list[Finding]:
    findings = []
    for top in SCAN:
        for file in sorted((root / top).rglob("*.py")):
            rel = file.relative_to(root).as_posix()
            findings += check_source(file.read_text(), rel)
    missing = sorted(m for m in PURE_MODULES if not (root / m).exists())
    if missing:  # a pure module that moved would silently stop being checked
        raise FileNotFoundError(f"declared pure modules not found: {missing}")
    return findings


def main() -> int:
    findings = check_tree()
    for f in findings:
        print(f)
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
