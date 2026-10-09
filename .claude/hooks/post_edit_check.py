"""PostToolUse on Write|Edit|MultiEdit: lint and type-check the file just edited.

CI catches a defect minutes after a push. This catches it in the same turn
that wrote it: findings go back to the agent through exit code 2, before it
builds anything else on top. It is the same ruff and pyrefly configuration
CI gates on, so the agent sees in the turn exactly what CI would refuse.

It never blocks the edit (the edit has already happened). It reports.
"""

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", *args], cwd=cwd,
                          capture_output=True, text=True, timeout=60)


def findings(path: Path, root: Path) -> list[str]:
    """Problems in one edited file; [] if clean or not Python."""
    if path.suffix != ".py" or not path.exists():
        return []
    out = []
    lint = _run(["ruff", "check", "--output-format", "concise", "--quiet", str(path)], root)
    if lint.returncode not in (0, 1):
        out.append(f"ruff could not run (exit {lint.returncode}): {lint.stderr.strip()[:200]}")
    out += [ln for ln in lint.stdout.splitlines() if ln.strip()]
    if root in path.resolve().parents:
        types = _run(["pyrefly", "check", "--preset", "default", str(path)], root)
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
    if not file_path:
        return 0
    problems = findings(Path(file_path), root)
    if problems:
        print("Checks found problems in the file you just edited:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        return 2  # PostToolUse: stderr goes back to the agent
    return 0


if __name__ == "__main__":
    sys.exit(main())
