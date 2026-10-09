"""The Claude Code hooks in .claude/hooks are gates, so they are tested like code.

Each hook is loaded by path (they are scripts, not a package) and driven
through its pure functions or its stdin/stdout contract.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / ".claude" / "hooks"


def load(name: str):
    sys.path.insert(0, str(HOOKS))
    try:
        spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(HOOKS))


def run_hook(name: str, payload: dict | str) -> dict | None:
    """Run a hook as Claude Code does: JSON on stdin, decision on stdout."""
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    r = subprocess.run(
        [sys.executable, str(HOOKS / f"{name}.py")],
        input=stdin, capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def denied(decision: dict | None) -> bool:
    return bool(decision) and decision["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- guard_gates: the gates cannot be edited inside a gated turn ------------

@pytest.mark.parametrize("path", [
    ".claude/hooks/guard_git.py",
    ".claude/settings.json",
    ".github/workflows/ci.yml",
    "ruff.toml",
    "pyrefly.toml",
    "tools/mutation_check.py",
    "/abs/checkout/tools/mutation_check.py",
])
def test_editing_a_gate_is_refused(path):
    ok, why = load("guard_gates").edit_allowed(path)
    assert not ok and why


@pytest.mark.parametrize("path", [
    "app/services.py",
    "tests/test_work_orders.py",  # test-first needs tests writable
    "README.md",
    "tools/complexity.py",
])
def test_editing_ordinary_code_is_allowed(path):
    assert load("guard_gates").edit_allowed(path) == (True, "")


def test_a_payload_with_no_path_is_refused_not_waved_through():
    ok, _ = load("guard_gates").edit_allowed(None)
    assert not ok


def test_gate_hook_denies_through_its_stdin_contract():
    assert denied(run_hook("guard_gates", {
        "tool_name": "Edit", "tool_input": {"file_path": str(ROOT / "ruff.toml")}}))
    assert run_hook("guard_gates", {
        "tool_name": "Edit", "tool_input": {"file_path": str(ROOT / "app/db.py")}}) is None


def test_gate_hook_denies_an_unreadable_payload():
    assert denied(run_hook("guard_gates", "{not json"))


# --- guard_git: commands that quietly destroy work -------------------------

@pytest.mark.parametrize("command", [
    "git add -A",
    "git add .",
    "git add --all",
    "cd /tmp && git add -A",
    "ls\ngit add -A",
])
def test_staging_everything_is_refused(command):
    assert denied(run_hook("guard_git", {"tool_input": {"command": command}, "cwd": str(ROOT)}))


@pytest.mark.parametrize("command", [
    "git add app/services.py tests/test_work_orders.py",
    "git commit -m 'never use git add -A; stage paths'",
    'grep -E "add|commit" notes.txt',
    "git checkout main",
])
def test_safe_commands_are_allowed(command):
    assert run_hook("guard_git", {"tool_input": {"command": command}, "cwd": str(ROOT)}) is None


def test_splitter_respects_quotes_and_heredocs():
    shared = load("guard_shared")
    assert shared.commands('echo "a | b" && git status') == ['echo "a | b"', "git status"]
    assert shared.commands("git commit -F - <<MSG\ngit add -A here is prose\nMSG") == [
        "git commit -F - <<MSG"
    ]


# --- post_edit_check: findings reach the agent the moment it edits ---------

def test_post_edit_check_reports_a_ruff_finding_in_the_edited_file(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def f(unused):\n    return 1\n")
    problems = load("post_edit_check").findings(bad, ROOT)
    assert any("ARG001" in p for p in problems)


def test_post_edit_check_is_silent_on_a_clean_file(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("def f(x: int) -> int:\n    return x\n")
    assert load("post_edit_check").findings(good, ROOT) == []


def test_post_edit_check_ignores_non_python_files(tmp_path):
    note = tmp_path / "notes.md"
    note.write_text("def f(unused): pass\n")
    assert load("post_edit_check").findings(note, ROOT) == []
