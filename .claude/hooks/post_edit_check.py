"""PostToolUse on Write|Edit|MultiEdit: lint and type-check the file just edited.

CI catches a defect minutes after a push. This catches it in the same turn
that wrote it: findings go back to the agent through exit code 2, before it
builds anything else on top. It is the same ruff and pyrefly configuration
CI gates on, so the agent sees in the turn exactly what CI would refuse.

It never blocks the edit (the edit has already happened). It reports.

THE INTERPRETER. The hook is launched by whatever `python3` is on PATH, which
need not have ruff, pyrefly or the project's deps. So it runs the checks with
the project venv's python, found by OS (F2), and tells pyrefly that python
explicitly: left to itself, pyrefly asks the first python on PATH for
site-packages and reports false missing-import errors (F3). With no venv, it
says the in-turn layer is off, rather than going quiet.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def venv_python(root: Path, os_name: str) -> Path:
    """The project venv's interpreter, where `python -m venv .venv` puts it on that OS."""
    if os_name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _run(python: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([python, "-m", *args], cwd=cwd,
                          capture_output=True, text=True, timeout=60)


def findings(path: Path, root: Path, python: str = sys.executable) -> list[str]:
    """Problems in one edited file; [] if clean or not Python. `python` must
    have ruff, pyrefly and the project's deps installed."""
    if path.suffix != ".py" or not path.exists():
        return []
    if root not in path.resolve().parents:
        return []  # not this project's file: its config does not apply (US-012)
    out = []
    lint = _run(python, ["ruff", "check", "--output-format", "concise", "--quiet", str(path)], root)
    if lint.returncode not in (0, 1):
        out.append(f"ruff could not run (exit {lint.returncode}): {lint.stderr.strip()[:200]}")
    out += [ln for ln in lint.stdout.splitlines() if ln.strip()]
    # A hook imports its siblings by directory, as Claude Code runs it;
    # check_types adds the same search path for the hooks.
    hooks = root / ".claude" / "hooks"
    siblings = ["--search-path", str(hooks)] if path.resolve().parent == hooks.resolve() else []
    types = _run(python, ["pyrefly", "check", "--preset", "default", *siblings,
                          "--python-interpreter-path", python, str(path)], root)
    out += [ln for ln in types.stdout.splitlines() if ln.startswith("ERROR")]
    return out


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError as exc:
        print(f"post_edit_check could not read its payload: {exc}", file=sys.stderr)
        return 1  # non-blocking error, shown to the user
    root = Path(data.get("cwd") or ".").resolve()
    file_path = (data.get("tool_input") or {}).get("file_path")
    if not file_path or Path(file_path).suffix != ".py":
        return 0
    python = venv_python(root, os.name)
    if not python.exists():
        print(f"in-turn checks are NOT running: no venv at {python.parent.parent}. "
              f"Create it (PRD P-2).", file=sys.stderr)
        return 2
    problems = findings(Path(file_path), root, str(python))
    if problems:
        print("Checks found problems in the file you just edited:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        return 2  # PostToolUse: stderr goes back to the agent
    return 0


if __name__ == "__main__":
    sys.exit(main())
