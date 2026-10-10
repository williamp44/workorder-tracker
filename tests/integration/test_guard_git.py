"""guard_git judged against a real repo: the probe tables of PRD_HARNESS_HARDENING.

The probes (docs/evidence/harness_probes_2026-10-09.md) found commands that
destroy uncommitted work, or stage everything, and that the guard let
through. Each row is driven through the hook's stdin contract, against a
throwaway repo whose dirty files make the dirty-path checks real.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "guard_git.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    """f.txt is committed, then made dirty. sub/x.txt is committed and clean."""
    root = tmp_path_factory.mktemp("repo")
    git(root, "init", "-q")
    git(root, "config", "user.email", "p@p")
    git(root, "config", "user.name", "p")
    (root / "sub").mkdir()
    (root / "f.txt").write_text("a")
    (root / "sub" / "x.txt").write_text("a")
    git(root, "add", "f.txt", "sub/x.txt")
    git(root, "commit", "-q", "-m", "init")
    (root / "f.txt").write_text("DIRTY")
    return root


def denied(repo: Path, command: str, tool: str = "Bash") -> bool:
    env = {k: v for k, v in os.environ.items() if k != "GATE_EDIT"}
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": str(repo)}),
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    return bool(r.stdout.strip()) and json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- US-005: find git inside wrappers, past global options, in PowerShell ----

@pytest.mark.parametrize("command", [
    "git -C . add -A",
    "git -c core.x=1 add -A",
    "git --no-pager add -A",
    "git.exe add -A",
    "git add -Av",
    "git add -uv",
    "git add :/",
    "git add -- :/",
    "git add ':(top)'",
    'bash -c "git add -A"',
    "sh -c 'git checkout -- f.txt'",
    "env git add -A",
    "& git add -A",
    "cmd /c git add -A",
    'pwsh -Command "git add -A"',
    'powershell -c "git add -A"',
    "git add `\n -A",
    "$(git add -A)",
])
def test_us005_refuses(repo, command):
    assert denied(repo, command)


@pytest.mark.control("pins the US-005 allow rows; the base allows them too, and the new parsing must not over-match")
@pytest.mark.parametrize("command", [
    "git commit -m 'mention git add -A here'",
    'grep -E "a|b" f.txt',
    "git status",
    "git checkout main",
    "git add f.txt",
    "git log -- .",
    "git diff -- sub",
    "echo '$(git add -A)'",
    # Found live: a heredoc body is stdin, not commands, $( ) included.
    "cat >> notes.txt <<'EOF'\nthe guard now refuses $(git add -A)\nEOF",
])
def test_us005_allows(repo, command):
    assert not denied(repo, command)
