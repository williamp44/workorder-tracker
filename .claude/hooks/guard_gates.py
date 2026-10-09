"""PreToolUse on Write|Edit|MultiEdit: a gate cannot check its own weakening.

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

Its limit, written down so it is not trusted past it: Bash is not covered.
A script can still write these files. This raises the cost of weakening a
gate from nothing to doing it visibly.
"""

import json
import sys
from pathlib import PurePath

sys.path.insert(0, str(PurePath(__file__).parent))
import guard_shared

GATES = (
    (".claude", "hooks"),
    (".claude", "settings.json"),
    (".github", "workflows"),
    ("ruff.toml",),
    ("pyrefly.toml",),
    ("tools", "mutation_check.py"),
)


def edit_allowed(path: str | None) -> tuple[bool, str]:
    """(may this file be edited through Write/Edit, why not)."""
    if not path or not path.strip():
        # Refused, not permitted: a check that cannot judge is not a check that passed.
        return False, "no file path in the payload, so this hook cannot tell whether a gate is being edited"
    parts = PurePath(path.replace("\\", "/")).parts
    for gate in GATES:
        n = len(gate)
        if any(parts[i:i + n] == gate for i in range(len(parts) - n + 1)):
            return False, (f"{'/'.join(gate)} is a gate, and a gate cannot check its own "
                           f"weakening. Ask the person to change it deliberately, outside "
                           f"this turn.")
    return True, ""


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw or "{}")
    except ValueError as exc:
        guard_shared.deny(f"this hook could not read its payload ({exc}), so it cannot "
                          f"tell whether a gate is being edited. Refused.")
        return 0
    if data.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return 0
    ok, why = edit_allowed((data.get("tool_input") or {}).get("file_path"))
    if not ok:
        guard_shared.deny(why)
    return 0


if __name__ == "__main__":
    sys.exit(main())
