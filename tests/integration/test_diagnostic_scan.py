"""The diagnostic guard (.claude/hooks/diagnostic_scan.py): fires, and stays quiet.

Ported from the guard built on host6. Every payload here is built from
payload_contract.json, which was RECORDED from a live Claude Code firing,
never written by hand. That is the point: the first version of the guard read
the key the documentation names (`tool_output`), which the harness does not
send, so it scanned nothing and reported clean, while its tests passed,
because they fed the shape the code expected.

Positives are diagnostics that were actually missed. Negatives are real
passing output from this repo, and matter more: a guard that fires on a clean
run teaches the reader to ignore it.
"""

import json
import subprocess
from types import MappingProxyType
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
HOOK = HOOKS / "diagnostic_scan.py"
PIN = json.loads((HOOKS / "payload_contract.json").read_text(encoding="utf-8"))
BS = chr(92)  # built, not typed, so a mangled heredoc cannot alter the fixtures


def payload(stdout: str = "", stderr: str = "", command: str = "python3 x.py") -> dict:
    """Exactly the pinned keys, so no fixture can assume a shape the harness does not send."""
    out: dict = {}
    for k in PIN["top_level_keys"]:
        if k == "tool_response":
            out[k] = {kk: ("" if kk in ("stdout", "stderr") else False) for kk in PIN["tool_response_keys"]}
            out[k]["stdout"], out[k]["stderr"] = stdout, stderr
        elif k == "tool_input":
            out[k] = {kk: "" for kk in PIN["tool_input_keys"]}
            out[k]["command"] = command
        elif k == "tool_name":
            out[k] = "Bash"
        elif k == "hook_event_name":
            out[k] = "PostToolUse"
        else:
            out[k] = ""
    return out


def run(data: dict | str) -> subprocess.CompletedProcess[str]:
    stdin = data if isinstance(data, str) else json.dumps(data)
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True)


def context(r: subprocess.CompletedProcess[str]) -> str:
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""


# --- must fire ------------------------------------------------------------

MUST_FIRE = MappingProxyType({
    # The incident in this repo: kept only the last line with `| tail -1`.
    "pyrefly's WARN that the hooks were never checked": (
        " INFO Checking project configured at `./pyrefly.toml`\n"
        " WARN Skipping include pattern `./.claude/hooks` because it is matched by `project-excludes` or an ignore file.\n"
        " INFO 0 errors (4 suppressed)\n"
    ),
    "the SyntaxWarning read past on host6": (
        "x.py:100: SyntaxWarning: \"is\" with 'str' literal. Did you mean \"==\"?\n"
        "  ok    reference trips no property\n"
    ),
    "a traceback buried above later output": (
        "Traceback (most recent call last):\n  File \"<string>\", line 7, in <module>\n"
        "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/x.bin'\nall done\n"
    ),
    "a command that was not found": "scripts/run.sh: line 81: setsid: command not found\n",
    "text decoded wrongly": "'utf-8' codec can't decode byte 0x97 in position 882: invalid start byte\n",
    "a deprecation nobody asked about": "/usr/lib/python3/foo.py:12: DeprecationWarning: ast.Str is deprecated\n",
    "a compiler-style error line": "error: cannot find symbol\n",
})


@pytest.mark.parametrize("label", list(MUST_FIRE))
def test_fires_on_a_real_diagnostic(label):
    r = run(payload(stdout=MUST_FIRE[label]))
    assert "unaddressed diagnostic" in context(r), label


def test_fires_when_the_diagnostic_arrives_on_stderr_only():
    r = run(payload(stderr=MUST_FIRE["a deprecation nobody asked about"]))
    assert "unaddressed diagnostic" in context(r)


# --- must stay quiet: this repo's own passing output ----------------------

MUST_BE_QUIET = MappingProxyType({
    "the suite passing": "collecting ... collected 174 items\n============ 174 passed in 2.61s ============\n",
    "ruff clean": "All checks passed!\n",
    "pyrefly clean": " INFO Checking project configured at `./pyrefly.toml`\n INFO 0 errors (4 suppressed)\n",
    "check_fp clean": "0 finding(s)\n",
    "check_red passing": "  base 7e45b323  head HEAD\n  72 new test(s), 1 declared control(s)\nOK   all 71 new test(s) were RED on the base code\n",
    "the mutation check, whose FAIL lines are its own verdicts": (
        "  control (no mutation)              pytest exit 0\n"
        "FAIL canary-docstring-only was killed but changes no behaviour: the kills are not trustworthy\n"
        "OK   control passed, equivalent canary survived, 19 of 19 mutants killed\n"
    ),
    "prose naming a warning class, with no colon after it": "this line names a SyntaxWarning above it: True\n",
    "git's line-ending advisory": "warning: in the working copy of 'a.py', LF will be replaced by CRLF the next time Git touches it\n",
    "an empty run": "",
})


@pytest.mark.parametrize("label", list(MUST_BE_QUIET))
def test_stays_quiet_on_a_verdict_or_clean_run(label):
    r = run(payload(stdout=MUST_BE_QUIET[label]))
    assert r.stdout.strip() == "", r.stdout


# --- hazards in the COMMAND, which no output pattern can see ---------------

HAZARDS = MappingProxyType({
    "a heredoc body with an escaped backslash": ("python3 - <<'PY'\ns = '" + BS + BS + "'\nPY", "heredoc"),
    "a heredoc body with a docstring continuation": ('cat > t.py <<"EOF"\nx = """' + BS + "\nEOF", "heredoc"),
    # The incident in this repo, verbatim.
    "stderr merged, then all but the last line dropped": (".venv/bin/pyrefly check 2>&1 | tail -1", "tail"),
    "stderr merged, then head": ("ruff check . 2>&1 | head -5", "tail"),
})

QUIET_COMMANDS = MappingProxyType({
    "a heredoc with no backslash in its body": "cat > notes.md <<'EOF'\n- plain text\nEOF",
    "backslashes in a path but no heredoc": "ls C:" + BS + "dev" + BS + "clojure",
    "truncation without merged stderr: a warning still shows": "pytest -q | tail -1",
    "a plain git command": "git log --oneline | head -5",
})


@pytest.mark.parametrize("label", list(HAZARDS))
def test_a_command_hazard_is_reported_even_when_the_output_is_clean(label):
    command, word = HAZARDS[label]
    ctx = context(run(payload(stdout="PASS (16 checks, 0 failed)\n", command=command)))
    assert "appear to succeed" in ctx and word in ctx, ctx


@pytest.mark.parametrize("label", list(QUIET_COMMANDS))
def test_an_ordinary_command_is_not_a_hazard(label):
    r = run(payload(stdout="all good\n", command=QUIET_COMMANDS[label]))
    assert r.stdout.strip() == "", r.stdout


# --- the payload contract: the guard must read what the harness sends ------

def test_the_recorded_contract_has_no_tool_output_key():
    # The documentation says it does. A guard built from the docs scanned nothing.
    assert "tool_output" not in PIN["top_level_keys"]
    assert "tool_response" in PIN["top_level_keys"]
    assert {"stdout", "stderr"} <= set(PIN["tool_response_keys"])
    assert "command" in PIN["tool_input_keys"]


def test_a_payload_with_exactly_the_pinned_shape_fires_and_reports_no_drift():
    ctx = context(run(payload(stdout=MUST_FIRE["a deprecation nobody asked about"])))
    assert "unaddressed diagnostic" in ctx and "CONTRACT" not in ctx


def test_the_documented_shape_still_works():
    data = payload()
    del data["tool_response"]
    data["tool_output"] = MUST_FIRE["a deprecation nobody asked about"]
    assert "unaddressed diagnostic" in context(run(data))


def test_a_payload_with_neither_key_is_loud_not_a_quiet_clean_run():
    data = payload()
    del data["tool_response"]
    r = run(data)
    assert r.returncode == 0 and "scanning NOTHING" in r.stderr


@pytest.mark.parametrize("change,expected", [
    ("drop tool_use_id", "tool_use_id"),
    ("add some_new_field", "some_new_field"),
])
def test_top_level_drift_is_reported(change, expected):
    data = payload(stdout="all good\n")
    if change.startswith("drop"):
        data.pop("tool_use_id")
    else:
        data["some_new_field"] = ""
    ctx = context(run(data))
    assert "SHAPE MOVED" in ctx and expected in ctx


def test_tool_response_changing_its_own_keys_is_reported():
    data = payload()
    data["tool_response"] = {"output": "x"}
    assert "tool_response keys moved" in context(run(data))


# --- robustness: reports, never blocks ------------------------------------

def test_unparseable_input_exits_0_and_says_so():
    r = run("not json at all")
    assert r.returncode == 0 and "could not parse" in r.stderr


def test_a_flood_is_deduplicated_and_capped():
    ctx = context(run(payload(stdout="Traceback (most recent call last):\n" * 50)))
    assert ctx.count("\n  L") < 15


def test_firing_still_exits_0():
    assert run(payload(stdout=MUST_FIRE["a compiler-style error line"])).returncode == 0
