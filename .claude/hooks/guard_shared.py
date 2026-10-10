"""What every hook needs, written once.

A hook runs as a script; Python puts the script's directory first on
sys.path, so sibling hooks import this module with no setup.
"""

import json
import os
import re
import shlex
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


def without_heredocs(line: str) -> str:
    """`line` with every heredoc body removed: a body is stdin, not commands."""
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
    """Each command in a compound shell line, quotes and heredocs respected.

    A PowerShell line continuation (a backtick before the newline) is joined
    first; otherwise `git add `<newline> -A` reads as two harmless commands."""
    joined = (line or "").replace("`\r\n", " ").replace("`\n", " ")
    return [c.strip() for c in _split_unquoted(without_heredocs(joined)) if c.strip()]


# --- finding the program a command really runs -------------------------------
# Bash and PowerShell both reach the shell hooks. These find a command behind
# its wrappers; a table, not a shell parser.

SHELLS = ("bash", "sh", "zsh", "dash", "pwsh", "powershell")
PREFIXES = ("&", "command", "exec")
CD = ("cd", "chdir", "pushd", "set-location", "sl")


def words(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd)
    except ValueError:  # unbalanced quotes: judge the plain split instead
        return cmd.split()


def program(word: str) -> str:
    """`/usr/bin/git`, `git.exe`, `C:\\...\\Git.EXE` -> `git`."""
    name = os.path.basename(word.replace("\\", "/")).casefold()
    return name[:-4] if name.endswith(".exe") else name


def short_flags(args: list[str]) -> str:
    """Every letter of every short-option cluster: `-fdx -n` -> `fdxn`."""
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def unwrap(w: list[str]) -> list[str]:
    """Drop the prefixes that run the rest of the line as a command:
    `env [VAR=x]`, `&`, `command`, `exec`, `cmd /c`."""
    while w:
        head = program(w[0])
        if head in PREFIXES:
            w = w[1:]
        elif head == "env":
            w = w[1:]
            while w and ("=" in w[0] or w[0].startswith("-")):
                w = w[1:]
        elif head == "cmd" and len(w) > 1 and w[1].casefold() == "/c":
            w = w[2:]
        else:
            return w
    return w


def shell_script(w: list[str]) -> str | None:
    """The `<s>` of `bash -c "<s>"` / `pwsh -Command "<s>"`; None if there is none."""
    for i, a in enumerate(w[1:], 1):
        flag = a.casefold()
        if flag in ("-c", "-command") or (flag.startswith("-") and not flag.startswith("--")
                                          and "c" in flag[1:] and program(w[0]) in SHELLS[:4]):
            return " ".join(w[i + 1:])
    return None


def subshells(line: str) -> list[str]:
    """The body of each `$( ... )` outside single quotes, where the shell runs it."""
    bodies, quote, i = [], None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            quote = None if ch == quote else quote
        elif ch == "'":
            quote = ch
        elif line.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(line) and depth:
                depth += {"(": 1, ")": -1}.get(line[j], 0)
                j += 1
            bodies.append(line[i + 2:j - 1] if depth == 0 else line[i + 2:])
            i = j
            continue
        i += 1
    return bodies
