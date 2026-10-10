"""PostToolUse and PostToolUseFailure on Bash|PowerShell: re-surface toolchain
diagnostics the reader skipped, from commands that passed and that failed.

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
     see: a heredoc body carrying backslashes.

PRECISION OVER RECALL. A guard that fires on a passing run teaches the reader
to ignore it, recreating the defect one level up. Bare `fail` is not a
pattern; only unsolicited toolchain diagnostics are. Patterns are added when
something was actually missed, with the incident named; never speculatively.

Exit 0 always: it reports, it never blocks. Ported from host6
(C:/dev/clojure/tools/hooks); docs/CHECKS.md records why it exists here.
"""

import datetime
import importlib.util
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import time

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
    # F8: pyrefly's `ERROR Cannot find module ...` (40+ lines in one output,
    # during F3) matched nothing. Its clean verdict is `INFO 0 errors`.
    (r"(?m)^\s*ERROR\b", "a tool logged an error"),
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
)
# Retired (US-015 Step 3): `stderr_merged_then_truncated`, a warning on
# `2>&1 | tail/head`. Measured over one run: 7 warned uses, 0 behaviour
# changes, and 17 `2>&1 | grep` uses it never saw. A warning that is read
# past teaches the reader to ignore hooks. The part that mattered, a commit
# gated on the filter's exit status, is refused by guard_git (US-014).

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
# A failed command fires PostToolUseFailure, whose payload has its own shape.
CONTRACT_FAILURE = HERE / "payload_contract_failure.json"
FAILURE_EVENT = "PostToolUseFailure"
# Pinned from a Bash payload, but absent from every PowerShell one (found
# live in US-001). The guard never reads it.
OPTIONAL_RESPONSE_KEYS = frozenset({"noOutputExpected"})
# Pinned from an interactive session, absent from every headless (`claude -p`)
# one, so every call in a ralph.sh run alarmed (found live in US-REVIEW-S3).
OPTIONAL_TOP_LEVEL_KEYS = frozenset({"scratchpad_dir"})

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


def contract_path(data: dict) -> pathlib.Path:
    """The pin for this payload's event."""
    return CONTRACT_FAILURE if data.get("hook_event_name") == FAILURE_EVENT else CONTRACT


def record_contract(data: dict) -> dict | None:
    """Record the live payload's SHAPE (key names only, never values)."""
    shape = {
        "recorded": datetime.datetime.now().isoformat(timespec="seconds"),
        "note": (f"Observed shape of the {data.get('hook_event_name') or 'PostToolUse'} payload. "
                 "Recorded from a live firing, NOT transcribed from documentation. "
                 "Delete this file to re-record."),
        **_shape(data),
    }
    try:
        with io.open(contract_path(data), "w", encoding="utf-8", newline="\n") as fh:
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
    contract = contract_path(data)
    if not contract.exists():
        shape = record_contract(data)
        if shape is None:
            return [f"could not record the payload contract to {contract.name}"]
        return [f"recorded a NEW payload contract in .claude/hooks/{contract.name} "
                f"(top-level: {', '.join(shape['top_level_keys'])}). Nothing has validated "
                f"it yet: confirm extract_output() reads the keys it lists."]
    try:
        pin = json.loads(contract.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"payload contract {contract.name} is unreadable ({exc})"]
    live = _shape(data)
    notes = []
    # Only a LOSS is reported (US-007). Every alarm seen live was an added key
    # (persistedOutputPath, backgroundTaskId, bashEditDiff, ...), all benign,
    # and a guard that cries wolf is read past.
    gone = [k for k in pin.get("top_level_keys") or []
            if k not in live["top_level_keys"] and k not in OPTIONAL_TOP_LEVEL_KEYS]
    if gone:
        notes.append(f"the hook payload SHAPE MOVED since it was pinned; keys gone: "
                     f"{', '.join(gone)}. Re-read extract_output() before trusting a quiet run.")
    pinned_tr, live_tr = pin.get("tool_response_keys"), live["tool_response_keys"]
    lost_tr = [k for k in pinned_tr or [] if k not in (live_tr or []) and k not in OPTIONAL_RESPONSE_KEYS]
    if pinned_tr is not None and live_tr is not None and lost_tr:
        notes.append(f"tool_response keys moved: lost {lost_tr}; pinned {pinned_tr}, live {live_tr}")
    elif pinned_tr is not None and live_tr is None:
        notes.append(f"tool_response is no longer a dict of {pinned_tr}")
    return notes


HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


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
    return hits


def extract_output(data: dict) -> str:
    """The command's output, from the payload the harness ACTUALLY sends.

    The documentation says `tool_output` (a string). The recorded payload
    carries `tool_response = {"stdout", "stderr", ...}` and no `tool_output`.
    Built from the docs, the guard read "", scanned nothing and reported
    clean. Both shapes are read; neither returns a sentinel, never "".

    A FAILED command fires PostToolUseFailure instead, and its recorded
    payload carries the output in `error`, with no `tool_response` (F4).
    """
    if data.get("hook_event_name") == FAILURE_EVENT and "error" in data:
        err = data["error"]
        return err if isinstance(err, str) else json.dumps(err)
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


EXIT_LINE = re.compile(r"(?m)^Exit code (-?\d+)\b")


def failure_line(data: dict) -> str | None:
    """`the command FAILED (exit n)` for a failed command; None otherwise.
    The payload has no exit-code key; the harness writes it into `error`."""
    if data.get("hook_event_name") != FAILURE_EVENT:
        return None
    m = EXIT_LINE.search(data.get("error") or "") if isinstance(data.get("error"), str) else None
    return f"the command FAILED (exit {m.group(1)})" if m else "the command FAILED"


def render(hits, cmd: str, cmd_hits=(), contract_notes=(), failed: str | None = None,
           written=()) -> str:
    out = [f"{failed}. Its output was scanned too:"] if failed else []
    if written:
        out.append("Python files written through a shell (post_edit_check did not see these):")
        out.extend(f"  {w}" for w in written)
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


# --- Python written through a shell (US-013) ---------------------------------
# post_edit_check fires on Write/Edit only. A .py file written by a heredoc
# or a patch script skipped the in-turn lint: an unused import got through
# a turn that way and was caught only by the full gate run.

SKIP_DIRS = frozenset((".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"))
MAX_WRITTEN = 5  # each check runs ruff and pyrefly; the hook has a 15 s budget
SLACK_S = 2      # clock and mtime granularity


def recently_written(root: pathlib.Path, since: float) -> list[pathlib.Path]:
    """The .py files under root whose mtime is at or after `since`."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                p = pathlib.Path(dirpath) / name
                try:
                    if p.stat().st_mtime >= since:
                        found.append(p)
                except OSError:
                    continue
    return sorted(found)


def _git(root: pathlib.Path, *args: str) -> str | None:
    """stdout of a git command, or None when git cannot answer (not a work tree)."""
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def committed_in_window(top: pathlib.Path, since: float) -> set[pathlib.Path] | None:
    """Files changed by plain commits made since `since`, judged from the reflog.

    Only `commit:` and `commit (initial):` entries count. If any other entry
    (rebase, checkout, reset, merge, pull, an amend) falls in the window, the
    files were rewritten by git, not written by the shell, so nothing counts:
    PR 5's author rewrite was `rebase (pick)` + `commit (amend)` with identical
    trees. None when the reflog cannot be read.
    """
    out = _git(top, "reflog", "--date=unix", "--format=%H%x00%gd%x00%gs")
    if out is None:
        return None
    window = []
    for line in out.splitlines():
        sha, selector, subject = [*line.split("\x00"), "", ""][:3]
        stamp = re.search(r"@\{(\d+)\}", selector)
        if not stamp or int(stamp.group(1)) < since:
            break  # newest first: the first older entry ends the window
        window.append((sha, subject))
    if not all(s.startswith(("commit: ", "commit (initial): ")) for _, s in window):
        return set()
    changed = set()
    for sha, _ in window:
        names = _git(top, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha) or ""
        changed |= {(top / n).resolve() for n in names.splitlines() if n}
    return changed


def written_by_shell(root: pathlib.Path, files: list[pathlib.Path], since: float
                     ) -> tuple[list[pathlib.Path], bool]:
    """(the recently modified files whose CONTENT changed, judged by git).

    A file counts when it differs from HEAD (dirty or untracked) or a plain
    commit in this command's window changed it. A rebase, checkout, stash or
    touch gives a file a new mtime with content git already has; mtime alone
    reported all of them. The bool is False when git could not judge, and the
    files are then returned by mtime alone, which the message must say.
    """
    top_out = _git(root, "rev-parse", "--show-toplevel")
    if top_out is None:
        return files, False
    top = pathlib.Path(top_out.strip()).resolve()
    status = _git(top, "status", "--porcelain", "-z", "--untracked-files=all")
    committed = committed_in_window(top, since)
    if status is None or committed is None:
        return files, False
    dirty = set()
    for entry in status.split("\x00"):
        if len(entry) > 3 and entry[2] == " ":
            dirty.add((top / entry[3:]).resolve())
    keep = dirty | committed
    return [f for f in files if f.resolve() in keep], True


def shell_written(data: dict) -> list[str]:
    """post_edit_check's findings on the .py files this command wrote."""
    cwd, duration = data.get("cwd"), data.get("duration_ms")
    if not cwd or not isinstance(duration, (int, float)):
        return []
    root = pathlib.Path(cwd).resolve()
    since = time.time() - duration / 1000 - SLACK_S
    files, judged_by_git = written_by_shell(root, recently_written(root, since), since)
    if not files:
        return []
    try:
        sys.path.insert(0, str(HERE))
        import post_edit_check
    except Exception as exc:
        return [f"could not check {len(files)} file(s): {type(exc).__name__}: {exc}"]
    venv = post_edit_check.venv_python(root, os.name)
    if venv.exists():
        python = str(venv)
    elif all(importlib.util.find_spec(m) for m in ("ruff", "pyrefly")):
        python = sys.executable  # CI and mutation copies have no .venv
    else:
        return []  # post_edit_check already says loudly that the layer is off
    out = [p for f in files[:MAX_WRITTEN] for p in post_edit_check.findings(f, root, python)]
    if len(files) > MAX_WRITTEN:
        out.append(f"... and {len(files) - MAX_WRITTEN} more file(s) not checked")
    if out and not judged_by_git:
        out.insert(0, "(not a git work tree: judged by mtime, so a file git rewrote may be listed)")
    return out


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
    written = shell_written(data)
    _trace(f"  output={len(out)} chars hits={len(hits)} cmd_hazards={cmd_hits} written={len(written)}")
    if not hits and not cmd_hits and not contract_notes and not written:
        return 0
    message = json.dumps({"hookSpecificOutput": {
        "hookEventName": data.get("hook_event_name") or "PostToolUse",
        "additionalContext": render(hits, cmd, cmd_hits, contract_notes, failure_line(data), written),
    }})
    sys.stdout.buffer.write((message + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
