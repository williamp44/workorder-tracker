"""The Claude Code hooks in .claude/hooks are gates, so they are tested like code.

Each hook is loaded by path (they are scripts, not a package) and driven
through its pure functions or its stdin/stdout contract.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"


def bare_python_first_on_path(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A copy of the project with no .venv in it, and an env whose first python
    has none of the project's deps: the conditions F3 was found under."""
    tree = tmp_path / "repo"
    shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", "*.db"))
    bare = tmp_path / "bare"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(bare)], check=True)
    bindir = bare / ("Scripts" if os.name == "nt" else "bin")
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("VIRTUAL_ENV", "PATH")}
    env["PATH"] = os.pathsep.join([str(bindir), os.environ.get("PATH", "")])
    return tree, env


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
    """Run a hook as Claude Code does: JSON on stdin, decision on stdout.

    GATE_EDIT is dropped: a session launched with it to change the gates
    would otherwise open them here too, and the deny tests would fail."""
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    env = {k: v for k, v in os.environ.items() if k != "GATE_EDIT"}
    r = subprocess.run(
        [sys.executable, str(HOOKS / f"{name}.py")],
        input=stdin, capture_output=True, text=True, cwd=ROOT, env=env,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def denied(decision: dict | None) -> bool:
    return bool(decision) and decision["hookSpecificOutput"].get("permissionDecision") == "deny"


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


def test_gate_hook_judges_notebook_edits_by_their_notebook_path():
    # NotebookEdit carries notebook_path, not file_path (F6).
    assert denied(run_hook("guard_gates", {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": str(ROOT / ".claude/hooks/x.ipynb")}}))


def test_gate_hook_denies_an_unreadable_payload():
    assert denied(run_hook("guard_gates", "{not json"))


def test_settings_local_json_is_a_gate():
    # Its `disableAllHooks` and `env` keys can switch every gate off.
    ok, why = load("guard_gates").edit_allowed(".claude/settings.local.json")
    assert not ok and why


def run_gates_launched_with(gate_edit: str | None, payload: dict) -> dict | None:
    """guard_gates as Claude Code runs it, in a process launched with or
    without GATE_EDIT. A hook inherits the launch env; a Bash call cannot set it."""
    env = {k: v for k, v in os.environ.items() if k != "GATE_EDIT"}
    if gate_edit is not None:
        env["GATE_EDIT"] = gate_edit
    r = subprocess.run([sys.executable, str(HOOKS / "guard_gates.py")],
                       input=json.dumps(payload), capture_output=True, text=True, cwd=ROOT, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


GATE_EDIT_PAYLOAD = MappingProxyType({"tool_name": "Edit", "tool_input": {"file_path": str(ROOT / "ruff.toml")}})


def test_a_launch_override_lets_a_person_open_the_gates_and_says_so():
    decision = run_gates_launched_with("1", dict(GATE_EDIT_PAYLOAD))
    assert not denied(decision)
    assert decision is not None and "GATE_EDIT" in decision["hookSpecificOutput"]["additionalContext"]


@pytest.mark.control("pins that only the exact value 1 opens the gates; base denies all of these")
@pytest.mark.parametrize("value", [None, "0", "", "true", "yes"])
def test_anything_but_gate_edit_1_keeps_the_gates_shut(value):
    assert denied(run_gates_launched_with(value, dict(GATE_EDIT_PAYLOAD)))


@pytest.mark.control("pins that the override never excuses a payload the hook cannot judge")
def test_the_override_does_not_wave_through_a_payload_with_no_path():
    assert denied(run_gates_launched_with("1", {"tool_name": "Edit", "tool_input": {}}))


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


@pytest.mark.control("pins that guard_git judges the command, whichever shell tool sent it (F1)")
def test_staging_everything_from_powershell_is_refused():
    assert denied(run_hook("guard_git", {
        "tool_name": "PowerShell", "tool_input": {"command": "git add -A"}, "cwd": str(ROOT)}))


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


def test_post_edit_check_finds_the_venv_python_for_each_os():
    venv_python = load("post_edit_check").venv_python
    assert venv_python(Path("r"), "nt") == Path("r") / ".venv" / "Scripts" / "python.exe"
    assert venv_python(Path("r"), "posix") == Path("r") / ".venv" / "bin" / "python"


def test_post_edit_check_is_silent_on_a_clean_file_whatever_python_is_on_path(tmp_path):
    # F3: pyrefly asked the first python on PATH for site-packages. Without an
    # in-repo .venv for it to find, a python lacking the deps gave false
    # missing-import ERRORs on a clean file.
    tree, env = bare_python_first_on_path(tmp_path)
    code = ("import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]);"
            "import post_edit_check as p;"
            "print(json.dumps(p.findings(Path(sys.argv[2]) / 'app' / 'services.py', Path(sys.argv[2]))))")
    r = subprocess.run([sys.executable, "-c", code, str(HOOKS), str(tree)], cwd=tree,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == []


def test_post_edit_check_says_the_layer_is_off_when_there_is_no_venv(tmp_path):
    edited = tmp_path / "edited.py"
    edited.write_text("x = 1\n")
    r = subprocess.run(
        [sys.executable, str(HOOKS / "post_edit_check.py")],
        input=json.dumps({"cwd": str(tmp_path), "tool_input": {"file_path": str(edited)}}),
        capture_output=True, text=True)
    assert r.returncode == 2
    assert "NOT running" in r.stderr and str(tmp_path / ".venv") in r.stderr


def test_post_edit_check_ignores_non_python_files(tmp_path):
    note = tmp_path / "notes.md"
    note.write_text("def f(unused): pass\n")
    assert load("post_edit_check").findings(note, ROOT) == []
