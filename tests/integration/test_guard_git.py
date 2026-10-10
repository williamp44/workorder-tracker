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


# --- US-006: every discard form, cwd drift, aliases, --staged -----------------

@pytest.fixture(scope="module")
def dirty(tmp_path_factory) -> Path:
    """sub/x.txt committed then made dirty; f.txt committed and clean; u.txt
    untracked; a repo-local alias aa = add -A."""
    root = tmp_path_factory.mktemp("dirty")
    git(root, "init", "-q")
    git(root, "config", "user.email", "p@p")
    git(root, "config", "user.name", "p")
    (root / "sub").mkdir()
    (root / "f.txt").write_text("a")
    (root / "sub" / "x.txt").write_text("a")
    git(root, "add", "f.txt", "sub/x.txt")
    git(root, "commit", "-q", "-m", "init")
    git(root, "config", "alias.aa", "add -A")
    (root / "sub" / "x.txt").write_text("DIRTY")
    (root / "u.txt").write_text("untracked")
    return root


@pytest.fixture(scope="module")
def clean(tmp_path_factory) -> Path:
    """Everything committed on branch main; nothing untracked."""
    root = tmp_path_factory.mktemp("clean")
    git(root, "init", "-q")
    git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    git(root, "config", "user.email", "p@p")
    git(root, "config", "user.name", "p")
    (root / "f.txt").write_text("a")
    git(root, "add", "f.txt")
    git(root, "commit", "-q", "-m", "init")
    return root


@pytest.mark.parametrize("command", [
    "git checkout sub/x.txt",
    "git checkout .",
    "git checkout HEAD sub/x.txt",
    "git checkout -f",
    "git checkout --force main",
    "git switch --discard-changes main",
    "git switch -f main",
    "git reset --hard",
    "git reset --hard HEAD~1",
    "git clean -fd",
    "git clean -fdx",
    "git stash drop",
    "git stash clear",
    "cd sub && git checkout -- x.txt",
    "cd sub && git restore x.txt",
    "Set-Location sub; git restore x.txt",
    "git aa",
])
def test_us006_refuses_on_a_dirty_tree(dirty, command):
    assert denied(dirty, command)


def test_us006_restoring_only_the_index_is_allowed(dirty):
    # Index only; the worktree copy is untouched. A false deny on the base.
    assert not denied(dirty, "git restore --staged sub/x.txt")


@pytest.mark.control("pins the US-006 allow rows that need no change; base allows them")
@pytest.mark.parametrize("command", [
    "git checkout main",
    "git checkout -b new",
    "git switch main",
    "git reset --hard",
    "git clean -fd",
])
def test_us006_allows_on_a_clean_tree(clean, command):
    assert not denied(clean, command)


@pytest.mark.control("pins that a checkout of a clean file stays allowed; base allows it")
def test_us006_allows_restoring_a_clean_file(dirty):
    assert not denied(dirty, "git checkout -- f.txt")


# --- US-014: a commit gated on a filter's exit status ------------------------
# A pipeline's status is its last stage's: `pytest | tail -2 && git commit`
# commits after a failing suite, because tail exited 0.

GATED_ON_A_FILTER = (
    "pytest -q 2>&1 | tail -2 && git commit -m x",
    'pytest -q | grep -E "passed|failed" && git add a.py && git commit -m x',
    "ruff check . | head -5 && git push",
    "python -m tools.check_red --base main | tail -1 && git commit -m x",
)


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize("command", GATED_ON_A_FILTER)
def test_us014_refuses_a_commit_gated_on_a_filter(repo, command, tool):
    assert denied(repo, command, tool)


@pytest.mark.control("pins the US-014 allow rows: pipefail, no filter, no commit, separate statements, quoted, heredoc")
@pytest.mark.parametrize("command", [
    "set -o pipefail; pytest -q | tail -2 && git commit -m x",
    "pytest -q && git commit -m x",
    "git log | head -5 && git status",
    "pytest -q | tail -2; git status",
    'git commit -m "a | tail && git commit"',
    "cat >> notes.txt <<'EOF'\nx | tail && git commit\nEOF",
])
def test_us014_allows(repo, command):
    assert not denied(repo, command)
