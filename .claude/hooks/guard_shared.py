"""What every hook needs, written once.

A hook runs as a script; Python puts the script's directory first on
sys.path, so sibling hooks import this module with no setup.
"""

import json
import re
from typing import IO, Any


def payload(stream: IO[str]) -> tuple[dict[str, Any] | None, str | None]:
    """(the hook payload, why not): exactly one of the two is None.

    A pair, not a bare None, so "stdin carried something unreadable" stays
    distinguishable from "read it, nothing to do". When a broken input and an
    absent one return the same value, no caller can tell them apart.
    """
    try:
        return json.load(stream), None
    except (OSError, ValueError) as exc:
        return None, f"stdin did not carry a JSON payload: {exc}"


def deny(reason: str) -> None:
    """Print a PreToolUse deny decision."""
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


# `<<TAG`, `<<'TAG'`, `<<"TAG"`, `<<-TAG`: the body that follows is stdin
# (a commit message, a JSON payload), not a list of commands.
HEREDOC = re.compile(r"""<<-?\s*(?P<q>['"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)""")
SEPARATORS = ("&&", "||", ";", "|", "\n")


def _without_heredocs(line: str) -> str:
    out, skip_to = [], None
    for raw in line.split("\n"):
        if skip_to is not None:
            if raw.strip() == skip_to:
                skip_to = None
            continue
        out.append(raw)
        found = HEREDOC.search(raw)
        if found:
            skip_to = found.group("tag")
    return "\n".join(out)


def _split_unquoted(text: str) -> list[str]:
    """Cut at every separator that is not inside quotes.

    Splitting the raw string made `grep -E "a|b"` look like two commands, and
    made a commit message mentioning `git add -A` look like the command.
    """
    out, buf, quote, i = [], [], None, 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        for sep in SEPARATORS:
            if text.startswith(sep, i):
                out.append("".join(buf))
                buf = []
                i += len(sep)
                break
        else:
            buf.append(ch)
            i += 1
    out.append("".join(buf))
    return out


def commands(line: str) -> list[str]:
    """Each command in a compound shell line, quotes and heredocs respected."""
    return [c.strip() for c in _split_unquoted(_without_heredocs(line or "")) if c.strip()]
