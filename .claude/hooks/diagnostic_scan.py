"""PostToolUse on Bash: re-surface toolchain diagnostics the reader skipped.

THE FAILURE IS POSITIONAL, NOT INFORMATIONAL. A diagnostic arrives at the TOP
of a command's output: it goes to stderr, which prints first, before the
summary. The reader, an AI agent included, scans the BOTTOM for the verdict
line ("174 passed", "0 errors") and has already decided the top is banner
noise. The warning was present, and was not read.

In this repo: `pyrefly check 2>&1 | tail -1` showed `INFO 0 errors` and threw
away, above it, `WARN Skipping include pattern .claude/hooks`, which said the
type gate had never checked a single hook. The same WARN was in CI's log for a
run that passed. On the machine this guard was first built on, Python printed
`SyntaxWarning: "is" with 'str' literal. Did you mean "=="?` (the exact fix,
for free, twice) above a block whose last line was read instead.

WHY A HOOK, NOT A RULE. "Read the warnings" in a prompt is care, and care is
what failed. This hook fires on every Bash result whether or not anyone
remembers it exists.

WHERE THE FINDINGS LAND. Through `hookSpecificOutput.additionalContext`,
attached directly after the tool's result, in the SAME turn: the agent's very
next model call sees the output and then these findings, before it acts on
the output. Not deferred to the next user turn. So the findings sit AFTER the
summary line, exactly where attention lands, which is the positional fix.

TWO SCANS.
  1. OUTPUT (`tool_response.stdout` and `.stderr`; the key is NOT what the
     docs say, see extract_output): high-precision toolchain diagnostics.
  2. COMMAND (`tool_input.command`): hazards that let a command appear to
     succeed while hiding or skipping something, which no output pattern can
     see. A heredoc body carrying backslashes, and stderr merged into stdout
     and then cut down with tail or head.

PRECISION OVER RECALL. A guard that fires on a passing run teaches the reader
to ignore it, recreating the defect one level up. Bare `fail` is not a
pattern; only unsolicited toolchain diagnostics are. Patterns are added when
something was actually missed, with the incident named; never speculatively.

Exit 0 always: it reports, it never blocks. Ported from host6
(C:/dev/clojure/tools/hooks); docs/CHECKS.md records why it exists here.
"""

import datetime
import io
import json
import os
import pathlib
import re
import sys

# Unsolicited toolchain diagnostics: something a tool emitted that the
# operator did not ask for, not a verdict the operator's own code printed.
PATTERNS = (
    # The colon is required: Python prints `file:line: SyntaxWarning: msg`,
    # and prose that merely names a warning class must not match.
    (r"\b\w*(?:Syntax|Deprecation|Runtime|User|Future|Resource|Bytes|Import|Unicode|Pending)Warning:",
     "runtime warning about your source"),
    (r"Traceback \(most recent call last\)", "unhandled exception"),
    (r"\bDid you mean\b", "the toolchain suggested a fix"),
    (r"command not found", "a command was not found"),
    (r"No such file or directory", "a path did not exist"),
    (r"bad interpreter", "line-ending or shebang damage"),
    (r"Permission denied", "permission denied"),
    (r"(?m)^\s*(?:warning|error|fatal error|fatal)\s*:", "compiler-style diagnostic"),
    # Incident here: pyrefly's `WARN Skipping include pattern .claude/hooks`.
    (r"(?m)^\s*(?:WARN|WARNING)\b", "a tool logged a warning"),
    (r"(?m)^\s*npm ERR!", "npm error"),
    (r"error\[E\d+\]", "rustc error"),
    (r"(?m)\berror TS\d+\b", "TypeScript error"),
    (r"Segmentation fault|core dumped", "crash"),
    (r"\r(?!\n)|\^M", "carriage return in output"),
    (r"(?:codec can't|can't decode|invalid start byte|UnicodeDecodeError)", "text decoded wrongly"),
    (r"(?i)\bskipp?(?:ed|ing)\b.*\b(?:test|check|suite|runtime)\b", "something was skipped"),
    (r"SyntaxError:\s*(?:unterminated|invalid|EOL|EOF|unexpected)",
     "source was mangled before the interpreter saw it"),
    (r"unexpected EOF while looking for matching", "unbalanced quote: the shell ate a delimiter"),
    (r"AssertionError:\s*0\b", "a substitution matched 0 times: the patch did NOT apply"),
)

COMMAND_HAZARDS = (
    ("heredoc_backslash",
     "this command pipes a heredoc whose body contains a BACKSLASH. Backslashes "
     "can be eaten between the tool call and the shell, sometimes silently: a "
     "patch script aborts before writing and the surrounding command still "
     "prints a plausible success. Confirm the file actually changed before "
     "believing it; prefer the Write/Edit tools for source."),
    ("stderr_merged_then_truncated",
     "this command merges stderr into stdout (2>&1) and then keeps only part of "
     "it with tail or head. Diagnostics print FIRST, at the top; the summary "
     "prints last. This is exactly how a pyrefly WARN saying the hooks were "
     "never checked was thrown away in this repo. Read the whole output, or "
     "drop the truncation."),
)

# The operator's own verdict lines. Checked FIRST; a match suppresses the line.
BENIGN = (
    r"(?i)\b0 (?:failures?|errors?|warnings?)\b",
    r"(?i)\bfailing:\s*none\b",
    r"(?i)^\s*(?:ok|FAIL)\s+\S",   # this repo's own tool verdicts (mutation check, check_red)
    r"(?i)\bPASS\b.*\b0 failed\b",
    r"(?i)\bnot found\b.*\bexpected\b",
    r"(?i)\(none\)",
    r"LF will be replaced by CRLF",  # git's routine advisory names nothing to do
)

MAX_LINES = 12
MAX_LEN = 240
HERE = pathlib.Path(__file__).resolve().parent
CONTRACT = HERE / "payload_contract.json"

# Sentinel: the payload had neither `tool_response` nor `tool_output`, so the
# contract moved. Distinct from "" so it cannot read as a clean run.
NO_OUTPUT_KEY = "\x00no-output-key"


def _shape(data: dict) -> dict:
    tr, ti = data.get("tool_response"), data.get("tool_input")
    return {
        "top_level_keys": sorted(data),
        "tool_response_keys": sorted(tr) if isinstance(tr, dict) else None,
        "tool_input_keys": sorted(ti) if isinstance(ti, dict) else None,
    }


def record_contract(data: dict) -> dict | None:
    """Record the live payload's SHAPE (key names only, never values)."""
    shape = {
        "recorded": datetime.datetime.now().isoformat(timespec="seconds"),
        "note": ("Observed shape of the PostToolUse payload. Recorded from a live "
                 "firing, NOT transcribed from documentation. Delete this file to re-record."),
        **_shape(data),
    }
    try:
        with io.open(CONTRACT, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(shape, fh, indent=2)
            fh.write("\n")
    except OSError:
        return None
    return shape


def check_contract(data: dict) -> list[str]:
    """Compare this payload's shape with the recorded pin; report any drift.

    Red-green cannot catch a wrong premise shared by a test and its code. The
    pin is recorded from the live system and the tests are built from it, so
    a payload that moves is reported instead of silently scanned as empty.
    """
    if not CONTRACT.exists():
        shape = record_contract(data)
        if shape is None:
            return [f"could not record the payload contract to {CONTRACT.name}"]
        return [f"recorded a NEW payload contract in .claude/hooks/{CONTRACT.name} "
                f"(top-level: {', '.join(shape['top_level_keys'])}). Nothing has validated "
                f"it yet: confirm extract_output() reads the keys it lists."]
    try:
        pin = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"payload contract {CONTRACT.name} is unreadable ({exc})"]
    live = _shape(data)
    notes = []
    gone = [k for k in pin.get("top_level_keys") or [] if k not in live["top_level_keys"]]
    added = [k for k in live["top_level_keys"] if k not in (pin.get("top_level_keys") or [])]
    if gone or added:
        notes.append("the hook payload SHAPE MOVED since it was pinned"
                     + (f"; keys gone: {', '.join(gone)}" if gone else "")
                     + (f"; keys new: {', '.join(added)}" if added else "")
                     + ". Re-read extract_output() before trusting a quiet run.")
    pinned_tr, live_tr = pin.get("tool_response_keys"), live["tool_response_keys"]
    if pinned_tr is not None and live_tr is not None and pinned_tr != live_tr:
        notes.append(f"tool_response keys moved: pinned {pinned_tr}, live {live_tr}")
    elif pinned_tr is not None and live_tr is None:
        notes.append(f"tool_response is no longer a dict of {pinned_tr}")
    return notes


HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
MERGED_THEN_CUT = re.compile(r"2>&1\s*\|\s*(?:tail|head)\b(?!\s+-[fF]\b)")


def heredoc_bodies(cmd: str):
    """The body of each heredoc. Only the body matters: a path full of
    backslashes and no heredoc is not a hazard and must not fire."""
    for m in HEREDOC.finditer(cmd):
        rest = cmd[m.end():]
        end = re.search(r"(?m)^\s*%s\s*$" % re.escape(m.group(2)), rest)
        yield rest[:end.start()] if end else rest


def scan_command(cmd: str) -> list[str]:
    """Hazards visible in the command itself, before any output is read."""
    if not cmd:
        return []
    hits = []
    if any("\\" in body for body in heredoc_bodies(cmd)):
        hits.append("heredoc_backslash")
    if MERGED_THEN_CUT.search(cmd):
        hits.append("stderr_merged_then_truncated")
    return hits


def extract_output(data: dict) -> str:
    """The command's output, from the payload the harness ACTUALLY sends.

    The documentation says `tool_output` (a string). The recorded payload
    carries `tool_response = {"stdout", "stderr", ...}` and no `tool_output`.
    Built from the docs, the guard read "", scanned nothing and reported
    clean. Both shapes are read; neither returns a sentinel, never "".
    """
    tr = data.get("tool_response")
    if isinstance(tr, dict):
        return "\n".join(p for p in (tr.get("stdout") or "", tr.get("stderr") or "") if p)
    if isinstance(tr, str) and tr:
        return tr
    legacy = data.get("tool_output")
    if legacy is not None:
        return legacy if isinstance(legacy, str) else str(legacy)
    if tr is not None:
        return str(tr)
    return NO_OUTPUT_KEY


def scan(text: str) -> list[tuple[int, str, str]]:
    benign = [re.compile(p) for p in BENIGN]
    hits, seen = [], set()
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip() or any(b.search(line) for b in benign):
            continue
        for pat, why in PATTERNS:
            if re.search(pat, line):
                key = re.sub(r"\d+", "N", line.strip())[:MAX_LEN]
                if key not in seen:
                    seen.add(key)
                    hits.append((i, line.strip()[:MAX_LEN], why))
                break
    return hits


def render(hits, cmd: str, cmd_hits=(), contract_notes=()) -> str:
    out = []
    if contract_notes:
        out.append("PAYLOAD CONTRACT: the guard may be reading the wrong keys, so a quiet run proves nothing:")
        out.extend(f"  !! {n}" for n in contract_notes)
    if cmd_hits:
        why = dict(COMMAND_HAZARDS)
        out.append(f"{len(cmd_hits)} hazard(s) in the COMMAND you just ran. Not errors: ways this "
                   f"command can appear to succeed while hiding or skipping something:")
        out.extend(f"  ! {h}: {why.get(h, h)}" for h in cmd_hits)
    if hits:
        out.append(f"{len(hits)} unaddressed diagnostic line(s) in that output, which may sit ABOVE "
                   f"the summary line you read. Decide explicitly whether each matters before moving on.")
        if cmd:
            out.append(f"  command: {cmd[:200]}")
        out.extend(f"  L{n:<5} {line}\n          ^ {w}" for n, line, w in hits[:MAX_LINES])
        if len(hits) > MAX_LINES:
            out.append(f"  ... and {len(hits) - MAX_LINES} more")
    return "\n".join(out)


def _trace(msg: str) -> None:
    """Append to .claude/hooks/.fired.log when that file EXISTS.

    A hook that is not wired and a hook that found nothing look the same:
    silence. `touch .claude/hooks/.fired.log` makes the difference visible.
    """
    log = HERE / ".fired.log"
    if not (log.exists() or os.environ.get("CLAUDE_HOOK_TRACE")):
        return
    try:
        with io.open(log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        sys.stderr.write(f"diagnostic_scan: could not write trace to {log}\n")


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        sys.stderr.write("diagnostic_scan: could not parse hook input\n")
        return 0
    _trace(f"fired tool={data.get('tool_name')}")
    contract_notes = check_contract(data)
    for n in contract_notes:
        sys.stderr.write(f"diagnostic_scan: {n}\n")
    out = extract_output(data)
    if out == NO_OUTPUT_KEY:
        sys.stderr.write(f"diagnostic_scan: payload has neither 'tool_response' nor 'tool_output' "
                         f"(keys: {sorted(data)}). The guard is scanning NOTHING; fix "
                         f"extract_output() before trusting a quiet run.\n")
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "")
    hits, cmd_hits = scan(out), scan_command(cmd)
    _trace(f"  output={len(out)} chars hits={len(hits)} cmd_hazards={cmd_hits}")
    if not hits and not cmd_hits and not contract_notes:
        return 0
    message = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": render(hits, cmd, cmd_hits, contract_notes),
    }})
    sys.stdout.buffer.write((message + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
