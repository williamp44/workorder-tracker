"""Where to look next: the longest, deepest functions, ranked.

    python -m tools.complexity              # functions over the thresholds
    python -m tools.complexity --stats      # size bands for the whole repo

A REPORT, not a gate. A gate whose findings nobody is fixing this week is
noise, and noise is how a checker gets ignored. This is for choosing where
to read closely.

Carried over from a larger codebase where defects were measured against
function size: functions over 100 lines held defects at about 25 times the
rate of functions of 30 lines or fewer, and nesting depth predicted almost
nothing once it was measured from the AST instead of from indentation. On a
repo this small, expect it to report nothing over the thresholds; that is
the result, not a failure.
"""

import argparse
import ast
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ["app", "scripts", "tools", "tests", "alembic"]

LONG = 100
DEEP = 5

# Depth comes from the AST, not from leading whitespace: a wrapped call is
# indented to line up with its bracket, and a continuation line is not a
# nesting level.
NESTS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith,
         ast.Try, ast.ExceptHandler, ast.FunctionDef, ast.AsyncFunctionDef,
         ast.ClassDef, ast.Match)


def nesting(node: ast.AST, depth: int = 0) -> int:
    deepest = depth
    for child in ast.iter_child_nodes(node):
        step = 1 if isinstance(child, NESTS) else 0
        deepest = max(deepest, nesting(child, depth + step))
    return deepest


def functions(path: Path) -> list[tuple[str, int, int, int]]:
    """(name, first line, length, depth) for every function in one file.
    A file that does not parse raises: an unreadable file is not a clean one."""
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        (n.name, n.lineno, n.end_lineno - n.lineno + 1, nesting(n))
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def survey(root: Path = ROOT) -> list[tuple[str, str, int, int, int]]:
    rows = []
    for top in SCAN:
        for path in sorted((root / top).rglob("*.py")):
            rel = str(path.relative_to(root))
            rows += [(rel, *fn) for fn in functions(path)]
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats", action="store_true", help="size bands")
    args = ap.parse_args(argv)

    rows = survey()
    lens = [r[3] for r in rows]
    if args.stats:
        print(f"  {len(rows)} functions in {', '.join(SCAN)}")
        print(f"  median {statistics.median(lens):.0f} lines, longest {max(lens)}, "
              f"median depth {statistics.median(r[4] for r in rows):.0f}")
        for lo, hi in ((0, 30), (31, 100), (101, 10**6)):
            label = f"{lo}-{hi}" if hi < 10**6 else f"over {lo - 1}"
            print(f"    {label:>10} lines: {sum(lo <= n <= hi for n in lens):>4}")
        return 0

    hot = sorted((r for r in rows if r[3] > LONG or r[4] > DEEP),
                 key=lambda r: -(r[3] * r[4]))
    print(f"  {len(hot)} function(s) over {LONG} lines or deeper than {DEEP}")
    for f, name, line, length, depth in hot:
        print(f"  {length:>6} lines  depth {depth}  {name}  {f}:{line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
