"""PreToolUse on Write|Edit|MultiEdit|NotebookEdit: a gate cannot check its own weakening.

The gates are the files that decide whether work is correct: these hooks,
their registration, CI, the linter and type-checker configs, and the mutant
list. An agent that can quietly loosen one of them inside the turn it is
being judged in has no gate at all. So editing one through Write/Edit is
refused, and has to be done deliberately, by a person, outside the turn.

Tests are NOT on the list: test-first means the agent writes them. A test
weakened to pass is what the mutation check catches. If the weakened test
no longer kills a mutant, CI goes red.

It judges a PATH, which is in the payload and needs no understanding of the
work. Hooks that judged the work itself (is anything failing, is this a
TDD-shaped edit) were measured in another project: about 18 refusals and 0
defects caught. This is the one refusal that was unambiguously right.

THE OVERRIDE. A person who means to change the gates launches Claude Code
with GATE_EDIT=1 in its environment. A hook inherits the environment Claude
Code was launched with; a Bash call made inside the session cannot set it,
and settings.local.json, whose `env` key could, is itself a gate. Every edit
the override lets through is announced to the agent, so it is never silent.
Only the exact value "1" opens the gates, and it never excuses a payload
the hook cannot judge.

Its limit, written down so it is not trusted past it: Bash is not covered.
A script can still write these files. This raises the cost of weakening a
gate from nothing to doing it visibly.
"""

import json
import os
import sys
from pathlib import PurePath

OVERRIDE = "GATE_EDIT"


def refuse_crash(exc: BaseException) -> None:
    """A crashed PreToolUse hook exits 1, which lets the edit through, silently
    (US-011). So a crash refuses. Under the launch override it lets the edit
    through and SAYS so instead: refusing then would leave the agent unable to
    repair the hook it just broke. Inline, not guard_shared: that import may be
    what failed."""
    what = f"guard_gates crashed ({type(exc).__name__}: {exc})"
    if os.environ.get(OVERRIDE, "") == "1":
        decision = {"additionalContext": (f"{what}; edit allowed by {OVERRIDE}=1 so the hook "
                                          f"can be repaired. A person must review this change.")}
    else:
        decision = {"permissionDecision": "deny",
                    "permissionDecisionReason": f"{what}: refusing rather than guessing."}
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}}))


sys.path.insert(0, str(PurePath(__file__).parent))
try:
    import guard_shared
except Exception as import_error:  # a half-edited sibling must not switch this guard off
    refuse_crash(import_error)
    sys.exit(0)

GATES = (
    (".claude", "hooks"),
    (".claude", "settings.json"),
    (".claude", "settings.local.json"),
    (".github", "workflows"),
    ("ruff.toml",),
    ("pyrefly.toml",),
    ("pyproject.toml",),  # pytest's testpaths and addopts
    ("tools", "mutation_check.py"),
    ("tools", "check_red.py"),
    ("tools", "check_fp.py"),
    ("tools", "check_types.py"),
    ("tools", "isolation.py"),
    ("tests", "conftest.py"),  # enforces the control-test reason
)


def edit_allowed(path: str | None) -> tuple[bool, str]:
    """(may this file be edited through Write/Edit, why not)."""
    if not path or not path.strip():
        # Refused, not permitted: a check that cannot judge is not a check that passed.
        return False, "no file path in the payload, so this hook cannot tell whether a gate is being edited"
    # Casefolded: Windows and macOS file systems ignore case, so .Claude/Hooks
    # is .claude/hooks there (F6). On Linux this also refuses a new RUFF.TOML.
    parts = PurePath(path.replace("\\", "/").casefold()).parts
    for gate in GATES:
        n = len(gate)
        if any(parts[i:i + n] == gate for i in range(len(parts) - n + 1)):
            return False, (f"{'/'.join(gate)} is a gate, and a gate cannot check its own "
                           f"weakening. Ask the person to change it deliberately, outside "
                           f"this turn.")
    return True, ""


def announce(path: str) -> None:
    """Let a gate edit through under the launch override, and say so."""
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": (f"gate edit to {path} allowed by {OVERRIDE}=1, set when this "
                              f"session was launched. A person must review this change."),
    }}))


def main() -> int:
    try:
        return judge_payload()
    except Exception as exc:
        refuse_crash(exc)
        return 0


def judge_payload() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw or "{}")
    except ValueError as exc:
        guard_shared.deny(f"this hook could not read its payload ({exc}), so it cannot "
                          f"tell whether a gate is being edited. Refused.")
        return 0
    if data.get("tool_name") not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return 0
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    ok, why = edit_allowed(path)
    if ok:
        return 0
    if path and path.strip() and os.environ.get(OVERRIDE) == "1":
        announce(path)
    else:
        guard_shared.deny(why)
    return 0


if __name__ == "__main__":
    sys.exit(main())
