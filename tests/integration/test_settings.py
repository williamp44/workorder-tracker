"""The hook registration in .claude/settings.json is a gate, so it is tested.

A hook that is correct but never fires is no hook. These tests read the
matchers, because the scripts' own tests cannot see whether Claude Code
ever calls them. F1 in PRD_HARNESS_HARDENING: the PowerShell tool bypassed
every shell hook, because the matchers named Bash only.
"""

import json
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


def test_gate_hook_covers_notebook_edits():
    for tools in matchers_for("guard_gates.py"):
        assert {"Write", "Edit", "MultiEdit", "NotebookEdit"} <= tools, sorted(tools)
