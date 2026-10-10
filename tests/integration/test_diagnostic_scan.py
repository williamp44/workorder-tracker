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

import importlib.util
import json
import os
import shutil
import subprocess
import time
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
    return subprocess.run([sys.executable, "-B", str(HOOK)], input=stdin, capture_output=True, text=True)


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
    # F8: pyrefly's ERROR lines were never matched; these are F3's false
    # missing-import errors, as US-002's RED run printed them.
    "pyrefly ERROR lines": (
        "ERROR Cannot find module `sqlalchemy` [missing-import]\n"
        "  ERROR Could not import `op` from `alembic` [missing-module-attribute]\n"
        "ERROR Cannot find module `fastapi` [missing-import]\n"
        " INFO 3 errors\n"
    ),
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
    "pyrefly clean, as check_types prints it": " INFO 0 diagnostics (4 suppressed)\n INFO 0 diagnostics\n",
    "pytest -v, with test names that say error": (
        "tests/integration/test_hooks.py::test_a_crashing_git_guard_refuses_and_names_the_crash[NameError] PASSED [ 40%]\n"
        "tests/unit/test_errors.py::test_error_page_renders PASSED [ 41%]\n"
    ),
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
})

QUIET_COMMANDS = MappingProxyType({
    # US-015 Step 3: the truncation warning was retired. Measured: 7 warned
    # uses, 0 behaviour changes, 17 `| grep` uses it never saw. US-014's
    # refusal holds the part that mattered (a commit gated on a filter).
    "stderr merged, then all but the last line dropped": ".venv/bin/pyrefly check 2>&1 | tail -1",
    "stderr merged, then head": "ruff check . 2>&1 | head -5",
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


def test_a_lost_top_level_key_is_reported():
    data = payload(stdout="all good\n")
    data.pop("tool_use_id")
    ctx = context(run(data))
    assert "SHAPE MOVED" in ctx and "tool_use_id" in ctx


# US-007 (F7): every alarm seen live was an ADDED key, and every one was
# benign: 6 false alarms in one session. Only a loss can make the guard read
# the wrong thing, so only a loss is reported.

def test_an_added_top_level_key_is_not_an_alarm():
    data = payload(stdout="all good\n")
    data["some_new_field"] = ""
    assert "CONTRACT" not in context(run(data))


@pytest.mark.parametrize("extra", [
    ("persistedOutputPath", "persistedOutputSize"),   # a large output
    ("backgroundTaskId",),                            # a background command
    ("backgroundTaskId", "backgroundCwdHint"),
    ("bashEditDiff",),                                # a command that edited a file
    ("returnCodeInterpretation",),                    # non-zero exit reported as success
    ("backgroundTaskId", "timedOutAfterMs"),          # seen live in this PRD's run
])
def test_keys_the_harness_adds_to_tool_response_are_not_an_alarm(extra):
    data = payload(stdout="all good\n")
    data["tool_response"].update({k: "" for k in extra})
    assert "CONTRACT" not in context(run(data))


def test_a_powershell_result_without_no_output_expected_is_not_an_alarm():
    # Found live in US-001: PowerShell's tool_response never has it.
    data = payload(stdout="all good\n")
    data["tool_name"] = "PowerShell"
    del data["tool_response"]["noOutputExpected"]
    assert "CONTRACT" not in context(run(data))


def test_a_headless_session_without_a_scratchpad_is_not_an_alarm():
    # Found live in US-REVIEW-S3: `claude -p` payloads have no scratchpad_dir,
    # so every call in a headless run (ralph.sh) alarmed. The guard never reads it.
    data = payload(stdout="all good\n")
    del data["scratchpad_dir"]
    assert "CONTRACT" not in context(run(data))


@pytest.mark.control("pins that losing a key the guard reads still alarms; base alarms too")
def test_losing_stdout_is_still_an_alarm():
    data = payload(stdout="all good\n")
    del data["tool_response"]["stdout"]
    assert "tool_response keys moved" in context(run(data))


def test_tool_response_changing_its_own_keys_is_reported():
    data = payload()
    data["tool_response"] = {"output": "x"}
    assert "tool_response keys moved" in context(run(data))


# --- failed commands: PostToolUseFailure (F4) -------------------------------
# A non-zero exit does not fire PostToolUse; it fires PostToolUseFailure, with
# its own payload, pinned from a live firing in payload_contract_failure.json.

FAILURE_PIN = json.loads((HOOKS / "payload_contract_failure.json").read_text(encoding="utf-8"))


def failure_payload(error: str, command: str = "python3 x.py") -> dict:
    """Exactly the pinned keys of a failed command's payload."""
    out: dict = {}
    for k in FAILURE_PIN["top_level_keys"]:
        if k == "tool_input":
            out[k] = {kk: "" for kk in FAILURE_PIN["tool_input_keys"]}
            out[k]["command"] = command
        elif k == "tool_name":
            out[k] = "Bash"
        elif k == "hook_event_name":
            out[k] = "PostToolUseFailure"
        elif k == "is_interrupt":
            out[k] = False
        elif k == "error":
            out[k] = error
        else:
            out[k] = ""
    return out


def test_the_recorded_failure_contract_carries_the_output_in_error():
    assert "error" in FAILURE_PIN["top_level_keys"]
    assert "tool_response" not in FAILURE_PIN["top_level_keys"]


def test_a_diagnostic_in_a_failed_command_is_reported_as_a_failure():
    r = run(failure_payload("Exit code 3\nWARN live\n", command='echo "WARN live"; exit 3'))
    decision = json.loads(r.stdout)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PostToolUseFailure"
    assert "WARN live" in decision["additionalContext"]
    assert "the command FAILED (exit 3)" in decision["additionalContext"]
    assert "CONTRACT" not in decision["additionalContext"]


@pytest.mark.control("pins precision on failure payloads: a failed command with no diagnostic stays quiet")
def test_a_failed_command_with_no_diagnostic_stays_quiet():
    r = run(failure_payload("Exit code 1\n"))
    assert r.returncode == 0 and r.stdout.strip() == ""


# --- Python written through a shell (US-013) --------------------------------
# post_edit_check fires on Write/Edit only. A file written by a shell command
# (a heredoc, a patch script) skipped the in-turn lint; an F401 got through.

ROOT = HOOKS.parents[1]


def load_scan():
    sys.path.insert(0, str(HOOKS))
    writes = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # US-016: no .pyc for a live hook to read stale
    try:
        spec = importlib.util.spec_from_file_location("diagnostic_scan", HOOK)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = writes
        sys.path.remove(str(HOOKS))


def test_recently_written_finds_only_the_python_files_changed_since(tmp_path):
    old, new, note = tmp_path / "old.py", tmp_path / "pkg" / "new.py", tmp_path / "new.md"
    new.parent.mkdir()
    for f in (old, new, note):
        f.write_text("x = 1\n")
    os.utime(old, (1_000_000, 1_000_000))
    since = time.time() - 60
    assert load_scan().recently_written(tmp_path, since) == [new]


def shell_payload(project: Path, command: str) -> dict:
    data = payload(stdout="", command=command)
    data["cwd"], data["duration_ms"] = str(project), 500
    return data


def test_python_written_through_a_shell_is_checked(tmp_path):
    shutil.copy(ROOT / "ruff.toml", tmp_path / "ruff.toml")
    (tmp_path / "bad.py").write_text("def f(unused):\n    return 1\n")
    ctx = context(run(shell_payload(tmp_path, "python write_it.py")))
    assert "Python files written through a shell" in ctx and "ARG001" in ctx


@pytest.mark.control("pins precision: a command that writes no .py file adds nothing; base adds nothing")
def test_a_command_that_writes_no_python_reports_nothing(tmp_path):
    shutil.copy(ROOT / "ruff.toml", tmp_path / "ruff.toml")
    bad = tmp_path / "bad.py"
    bad.write_text("def f(unused):\n    return 1\n")
    os.utime(bad, (1_000_000, 1_000_000))  # written long before this command
    assert context(run(shell_payload(tmp_path, "ls"))) == ""


# --- robustness: reports, never blocks ------------------------------------

def test_unparseable_input_exits_0_and_says_so():
    r = run("not json at all")
    assert r.returncode == 0 and "could not parse" in r.stderr


def test_a_flood_is_deduplicated_and_capped():
    ctx = context(run(payload(stdout="Traceback (most recent call last):\n" * 50)))
    assert ctx.count("\n  L") < 15


def test_firing_still_exits_0():
    assert run(payload(stdout=MUST_FIRE["a compiler-style error line"])).returncode == 0
