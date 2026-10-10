"""The hook registration in .claude/settings.json is a gate, so it is tested.

A hook that is correct but never fires is no hook. These tests read the
matchers, because the scripts' own tests cannot see whether Claude Code
ever calls them. F1 in PRD_HARNESS_HARDENING: the PowerShell tool bypassed
every shell hook, because the matchers named Bash only.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / ".claude" / "settings.json"


def matchers_for(script: str) -> list[set[str]]:
    """The matcher of every hook entry that runs `script`, split on |."""
    hooks = json.loads(SETTINGS.read_text())["hooks"]
    found = [
        set(entry["matcher"].split("|"))
        for event in hooks.values()
        for entry in event
        for hook in entry["hooks"]
        if script in hook["command"]
    ]
    assert found, f"{script} is not registered in {SETTINGS}"
    return found


@pytest.mark.parametrize("script", ["guard_git.py", "diagnostic_scan.py"])
def test_shell_hooks_judge_every_shell_tool(script):
    for tools in matchers_for(script):
        assert {"Bash", "PowerShell"} <= tools, f"{script} matcher is {sorted(tools)}"


def test_failed_shell_commands_are_scanned_too():
    # F4: a non-zero exit fires PostToolUseFailure, never PostToolUse.
    hooks = json.loads(SETTINGS.read_text())["hooks"]
    assert any("diagnostic_scan.py" in hook["command"]
               for entry in hooks.get("PostToolUseFailure", [])
               for hook in entry["hooks"])


def session_start_commands() -> list[str]:
    hooks = json.loads(SETTINGS.read_text())["hooks"]
    return [hook["command"] for entry in hooks.get("SessionStart", []) for hook in entry["hooks"]]


def run_session_start(path_dir: Path) -> subprocess.CompletedProcess[str]:
    """The SessionStart check, run by bash with only `path_dir` on PATH."""
    bash = shutil.which("bash")
    assert bash, "bash is needed to run hook commands"
    (command,) = session_start_commands()
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PATH"] = str(path_dir)
    return subprocess.run([bash, "-c", command], capture_output=True, text=True, env=env)


def test_the_python3_check_does_not_itself_need_python3():
    # R1-1: every hook launches with python3. A check that is a python3
    # script could not report that python3 is missing; it is plain shell.
    (command,) = session_start_commands()
    assert ".py" not in command and "||" in command


def test_a_missing_python3_is_announced_at_session_start(tmp_path):
    r = run_session_start(tmp_path)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "python3" in out["systemMessage"] and "NOT running" in out["systemMessage"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "python3" in out["hookSpecificOutput"]["additionalContext"]


def test_a_working_python3_is_silent_at_session_start(tmp_path):
    shim = tmp_path / "python3"
    shim.write_text("#!/bin/sh\nexit 0\n")
    shim.chmod(0o755)
    r = run_session_start(tmp_path)
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_gate_hook_covers_notebook_edits():
    for tools in matchers_for("guard_gates.py"):
        assert {"Write", "Edit", "MultiEdit", "NotebookEdit"} <= tools, sorted(tools)
