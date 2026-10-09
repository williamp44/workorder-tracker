"""Type-check everything, including the hooks pyrefly would otherwise skip.

    python -m tools.check_types

Two pyrefly runs. The project, as configured in pyrefly.toml. Then the
Claude Code hooks as explicit files: pyrefly skips hidden directories such as
.claude whatever its excludes say, so a config entry for them claimed
coverage that never happened. The hooks import their siblings by directory,
as Claude Code runs them, hence the extra search path.

Warnings count: `--min-severity warn` makes them fail the gate.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The preset is pinned: with no config file in reach, pyrefly falls back to a
# lenient preset that reports nothing on a None passed to a str parameter.
PYREFLY = (sys.executable, "-m", "pyrefly", "check", "--preset", "default", "--min-severity", "warn")


def project_command() -> list[str]:
    return list(PYREFLY)


def hooks_command(root: Path = ROOT) -> list[str]:
    hooks = sorted(p.relative_to(root).as_posix() for p in (root / ".claude" / "hooks").glob("*.py"))
    if not hooks:  # an empty file list would pass without checking anything
        raise FileNotFoundError(f"no hook files under {root / '.claude' / 'hooks'}")
    return [*PYREFLY, "--search-path", ".claude/hooks", *hooks]


def main() -> int:
    codes = [subprocess.run(cmd, cwd=ROOT).returncode for cmd in (project_command(), hooks_command())]
    return 1 if any(codes) else 0


if __name__ == "__main__":
    sys.exit(main())
