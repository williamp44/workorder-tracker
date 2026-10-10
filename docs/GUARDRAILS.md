# Guardrails for AI-written code

This repo was written with an AI coding agent. The agent writes fluent code
that looks right to the thing that produced it, so care at the keyboard does
not catch its mistakes. What catches them is putting the work where being
wrong produces a visible disagreement: a test that goes red, a check that
fires, a database that refuses.

Two principles run through everything here:

1. **Rules are enforced by tools, not by asking the agent to follow them.**
   A rule written in a prompt or a style guide is a preference; it decays
   over a long session and nothing notices when it is broken. Every rule this
   repo cares about is a hook, a lint or type rule, an AST check, a CI gate,
   or a mutant that turns the suite red. The aim is to **prevent** a defect,
   or **catch it the moment it happens**: in the same turn if possible, in CI
   if not.
2. **Each new defect class becomes a check, so it cannot recur.** When a
   review or a check finds a kind of mistake nothing was looking for, the fix
   is not just the code: a rule, a test, a mutant or a hook is added so the
   same class is caught mechanically next time. The table at the end of this
   page is that history.

This page explains the method and each check in it. [CHECKS.md](CHECKS.md)
is the ledger: every defect found, which check found it, and the evidence.

## The method: oracle first

**Before writing code, decide how you will know it is correct.** That
decision is the *oracle*. It comes before the code, it is independent of the
code, and it has to be shown able to fail.

| Rule | Why | In this repo |
| --- | --- | --- |
| **State the oracle before the change.** | A result seen first gets rationalised. A result predicted first gets checked. | `tools/check_red.py` fails a pull request if any new test already passes on the base branch's code. |
| **The oracle must not be derived from the code under test.** | A test generated from the code shares the code's mistakes. | The transition spec in `tests/spec.py` is written out by hand. The first draft derived it from the table under test, so a wrong table produced matching wrong tests that passed. |
| **Prove the oracle can fail.** | A check that has only ever been green has proved nothing. It may never reach the code. | `tools/mutation_check.py` injects 47 bugs (`python -m tools.mutation_check` → `47 of 47 mutants killed`, at `8d8fc99`; full output in CHECKS.md). Each must turn the suite red. |
| **Check the checker.** | An instrument is code and has code's defect rate. | A mutant that changes no behaviour must *survive*. When the mutation tool's own self-test was killing every mutant, this canary is what exposes it (CHECKS.md, instrument defect 2). |
| **Measure a rule before trusting it.** | A plausible rule that is noisy gets switched off within a week, and takes the good rules with it. | Every check had to show two numbers before gating CI: does it fire on the known defects, and is it quiet on the current tree. |

### The oracles in this repo

| Oracle | Source of "correct" | What it catches |
| --- | --- | --- |
| Hand-written transition spec | the spec, written apart from the code | a wrong transition table |
| `alembic check` in `test_migrations.py` | the models | a migration that drifts from the models, server defaults included |
| The same suite on SQLite and MariaDB | a second database engine | behaviour that only holds on one engine (it found two on MariaDB 11) |
| Composite foreign key `(site_id, tenant_id)` | the database itself | a cross-tenant write that gets past a bug in the app |
| Mutation check | a list of known-wrong programs | tests that pass whatever the code does |
| Equivalent canary mutant | a program that is *not* wrong | a suite that fails for reasons other than behaviour |

### The cycle: RED, GREEN, VERIFY, LOCK, each one checked

| Step | Means | Enforced by |
| --- | --- | --- |
| **RED** | A new test fails against the code before the change. | `tools/check_red.py` in CI on every pull request. It builds the base branch's code, lays the new tests over it, and requires each new test to fail. A test that must stay green (it pins behaviour that has to keep working) declares `@pytest.mark.control("reason")`; the reason is required. |
| **GREEN** | The change makes it pass, and nothing else breaks. | the full suite, on SQLite and on MariaDB |
| **VERIFY** | Break the code on purpose and watch the test catch it. | `tools/mutation_check.py`: every mutant must be killed, the equivalent canary must survive |
| **LOCK** | The verified behaviour cannot quietly regress. | the test and its mutant are committed; `guard_gates` stops the agent editing the mutant list, CI or check configs inside a turn |

`check_red` audits history too: `python -m tools.check_red --base <rev>^ --head <rev>`.

### Functional core, imperative shell

Decisions are pure functions over immutable data; I/O lives at the edges.

| Where | What |
| --- | --- |
| `app/rules.py` | The transition decision. Pure: no database, no I/O, no async. The table is a read-only mapping of frozensets. |
| `app/schema_compare.py` | How server defaults compare. Pure. |
| `app/services.py` | The imperative shell: read, ask `rules`, write. Takes a session and mutates it, which is its job. |
| request bodies (`app/schemas.py`) | frozen pydantic models |
| every module-level constant | tuple, frozenset or `MappingProxyType` |

`tools/check_fp.py` enforces it, in the suite and in CI:

| Rule | Applies to | Catches |
| --- | --- | --- |
| `mutable-constant` | every file | a module-level `UPPER_CASE` list, dict or set any importer can change |
| `mutated-argument` | pure modules | a function changing its caller's data (item or attribute assignment, `del`, `.append()` and friends) |
| `impure-core` | pure modules | importing the database, web or OS layers; `async def`; `global` |
| `mock-in-unit-test` | `tests/unit/` | `unittest.mock`, `monkeypatch`, `mocker` |

**Mocks:** unit tests (`tests/unit/`) exercise pure code with plain values
and never mock; a pure function needs no stand-ins. Integration tests
(`tests/integration/`) use the real database and may substitute a
collaborator to stage something a real one cannot do on demand, such as a
second request arriving between a read and a write.

## The layers: prevent, catch in the turn, catch before merge

The earlier a defect is caught, the less is built on top of it.

### 1. Prevent: Claude Code hooks (`.claude/hooks/`, `.claude/settings.json`)

| Hook | When (matcher) | What it does |
| --- | --- | --- |
| `guard_gates.py` | before Write, Edit, MultiEdit, NotebookEdit | Refuses edits to the gates themselves: the hooks and their registration (`settings.json`, `settings.local.json`), CI, the ruff, pyrefly and pytest configs, `tests/conftest.py`, and the gate tools (`mutation_check`, `check_red`, `check_fp`, `check_types`, `isolation`). Paths match case-insensitively. A person who means to change a gate launches the session with `GATE_EDIT=1`; every edit that lets through is announced. |
| `guard_git.py` | before Bash and PowerShell | Refuses `git add -A`/`-Av`/`.`/`:/`/a directory, and every form that discards uncommitted work (`checkout` of paths with or without `--`, `restore`, `checkout -f`, `switch -f`, `reset --hard`, `stash drop/clear`, `clean -f` over untracked files). It finds git behind `env`, `&`, `cmd /c`, `bash -c`, `pwsh -Command`, `$( )`, global options, a `cd` earlier in the line and repo aliases. It also refuses a commit chained after `<check> \| tail` (the commit would be gated on `tail`'s exit status). |
| SessionStart check | when a session starts | Every hook launches with `python3`. If that does not start Python 3.11+ (on stock Windows it is the Store stub), it says so loudly, because a hook that cannot start does not block. |

A guard that crashes **refuses**: a PreToolUse hook that exits 1 lets the
call through, so a half-edited `guard_shared` once switched every guard off.
Under `GATE_EDIT=1`, a crashed `guard_gates` lets the edit through and says
so instead, so the hook can be repaired.

They judge a **path** or a **command**, facts in the payload that need no
understanding of the work. Hooks that tried to judge the work itself (is a
test failing, is this edit TDD-shaped) were measured in another project:
about 18 refusals and 0 defects caught. Those were not carried over.

**Tests are not gated.** Test-first means the agent writes tests. A test
weakened until it passes is caught by the mutation check: the mutant it used
to kill survives, and CI goes red.

**Limits.** The shell (Bash or PowerShell) is not covered by `guard_gates`:
a script can still write a gate file. The hook moves weakening a gate from
quiet to visible; it is not a wall. `guard_git` is table-driven, not a shell
parser. It does not see `eval`, scripts, `Start-Process git -ArgumentList`,
backtick command substitution, shell aliases (`!cmd`), or aliases defined
outside the repo. Every other probe case is held by a test in
`tests/integration/test_guard_git.py`.

### 2. Catch in the turn: `post_edit_check.py`

After every edit to a Python file, ruff and pyrefly run on that file and any
findings go straight back to the agent (exit code 2) before it builds
anything else on top. It uses the same configuration CI gates on, so the
agent sees in the turn what CI would refuse.

**Its interpreter.** The hook is launched by `python3`, which need not have
ruff, pyrefly or the deps. It runs the checks with the project venv's
python, `.venv/Scripts/python.exe` on Windows and `.venv/bin/python`
elsewhere, and passes that python to pyrefly explicitly. Left to itself,
pyrefly asks the first python on PATH for site-packages and reports false
`missing-import` errors. With no venv it exits 2 and says the in-turn layer
is NOT running. It judges only files inside the project. A `.py` file
written through the shell instead of Edit is checked by `diagnostic_scan`
after the command (below).

Evidence: pyrefly caught 4 defects in code written during this work: a
function call used as a type annotation, a mistyped lookup table, a
`.rowcount` the declared type does not have, and an `Optional` used unchecked
(CHECKS.md).

**And the diagnostics nobody reads: `diagnostic_scan.py`.** A tool can say
exactly what is wrong and still be ignored, because of *where* it says it.
Warnings print first, at the top; the summary prints last, at the bottom; the
reader, an AI agent included, scans the bottom for the verdict. That is how a
pyrefly `WARN` saying the hooks were never type-checked was missed twice. This
hook scans every Bash and PowerShell result, from commands that passed
(PostToolUse) **and** commands that failed (PostToolUseFailure, a separate
event with its own payload), for unsolicited toolchain diagnostics. It also
lints any `.py` file the command wrote. It attaches its findings directly
after the tool result, in the same turn: after the summary line, where
attention already lands. It reports and never blocks, and it is built for
precision, because a guard that fires on a passing run teaches the reader to
ignore it. A warning on `2>&1 | tail` was retired for that reason: measured
over one run, 7 warned uses changed behaviour 0 times. The part that
mattered, a commit gated on the filter's exit status, is refused by
`guard_git`.

Its tests are built from payload contracts **recorded** from live firings,
not from the documentation: the documented key (`tool_output`) is not what
the harness sends, and a guard built from the docs scanned nothing and
reported clean while its tests passed. A recorded key that goes **missing**
is reported on every firing. Keys the harness adds are not reported: every
alarm of that kind seen live was benign.

### 3. Catch before merge: CI (`.github/workflows/ci.yml`)

| Step | Leg | Gate |
| --- | --- | --- |
| `ruff check .` | SQLite | zero findings |
| `python -m tools.check_types` | SQLite | zero errors or warnings, project and hooks; each suppression carries a reason |
| `python -m tools.check_fp` | SQLite | zero findings |
| `pytest` | SQLite **and** MariaDB | all pass |
| `python -m tools.check_red` | SQLite, pull requests | every new test RED on the base code |
| `python -m tools.mutation_check` | SQLite | control passes, canary survives, every mutant killed |

### 4. Catch what checks cannot: review and new angles

Checks only answer questions somebody already asked. They **hold ground**;
they do not **gain** it. Every check above stops a defect class that was
already known. New classes are found by changing where the observer stands,
by looking from a new **angle**, not by running the same checks harder.

**Angles that work:**

- run it for real, end to end, on the real target (here, the production
  database engine);
- give the same evidence to a fresh reviewer told to break it, not to
  approve it;
- hand the output to the person who will use it;
- compare against an older artefact of the same kind;
- ask what an input is *for*, not only what shape it has;
- build the plausible worse version and see what notices;
- enumerate what the code *can* do, not just what it is meant to do;
- distrust a result nobody predicted, a kill or a pass, and ask what
  caused it;
- re-derive a number from a second source before believing the first.

**A fake angle asks the same question with more effort.** Running the suite
again, or asking the same reviewer to look harder, is not a new angle.

**When to stop:** move in *different* directions; stop after several
consecutive directions turn up nothing; write down every empty direction, so
nobody re-walks it.

**The angles that found defects in this repo** (each is in
[CHECKS.md](CHECKS.md)):

| Angle | What it found |
| --- | --- |
| An adversarial reviewer told to break each README claim, proving attacks on a copy | the status-change race, the CSRF hole, unbounded ids, blank names, `alembic check` ignoring server defaults |
| A Linus-style taste review | the duplicated error mapping, check-then-insert in `create_site` |
| Running on the production engine (MariaDB 11) instead of only SQLite | the race surfacing as error 1020; a false default-comparison difference introduced by a fix |
| A kill nobody predicted, and asking which test caused it | the mutation check killing every mutant with its own self-test |
| CI disagreeing with a local run, then reproducing it the way CI installs | `check_red` measuring the working copy instead of the base |
| A number disagreeing with a second source | the ruff measurement collapsing duplicate findings |
| Asking whether a first green proved anything | the RED gate failing a test that could only test test code |

**Turning an angle into a check.** An angle finds a defect once. The fix
includes making that class mechanical: a test, a mutant, a rule or a hook.
Then the next occurrence is caught without anyone standing in that spot
again. That is how every row of the table at the end of this page got there.

## What none of this does

- **It does not judge whether the requirement is right.** A green gate says
  the code does what the tests say. It says nothing about whether the tests
  say the right thing.
- **Mutation testing proves the tests assert something, not that what they
  assert is right.** A test that expects the wrong value kills mutants just as
  well as one that expects the right value. Only a source outside the code can
  settle that: the spec, the client, a published rule.
- **Generic linters catch little on their own.** ruff saw 3 of the first 4
  tenant-isolation bugs, and only because every service function takes
  `tenant_id`, so dropping its filter leaves the argument unused. A larger
  rule set carried over from another codebase (`check_discipline`, 15 rules)
  saw 0 of 4 and produced 2 false positives here, so it was not adopted.
- **Counts are catch volume, not an error rate.** Nothing here measures how
  many defects a human would have written in the same work.

## Defect classes, and the check that now stops each one

| Defect class | First found by | Now stopped by |
| --- | --- | --- |
| A query that forgets its tenant filter | mutation check (by design) | tests + 3 mutants; ruff `ARG001` (an unused `tenant_id`) |
| A test derived from the code it tests | a mutant that survived | the hand-written spec in `tests/spec.py` |
| Check-then-act race on a status change | adversarial review | conditional `UPDATE`; test; mutant |
| Cookie-authenticated POST open to CSRF | adversarial review | `HX-Request` guard; test; mutant |
| Unbounded ids and blank names | adversarial review | bounded and trimmed input types; tests; mutants |
| Migration drifting from the models | adversarial review | `alembic check` with server defaults; mutant |
| Behaviour that only holds on one database | CI on MariaDB | the suite runs on both engines |
| A function call used as a type, an unchecked `Optional` | pyrefly | pyrefly gate in CI and in the turn (`post_edit_check`) |
| A mutable module constant | `check_fp` | `mutable-constant` rule; mutant |
| A test written after the code, or one that cannot fail | `check_red` | `check_red` in CI; mutant |
| A mutation tool whose kills are not caused by behaviour | a kill nobody predicted | the equivalent canary; mutant runs exclude the tool's own tests |
| An agent loosening a gate it is judged by | design (measured in another project) | `guard_gates`; mutant |
| `git add -A`, or discarding uncommitted work | an agent in another project | `guard_git`; mutant |
| A stale waiver that suppresses nothing | ruff `RUF100` | ruff gate |
| A diagnostic printed at the top and not read, because the reader scans the bottom | the user rereading CI's log | `diagnostic_scan.py` (PostToolUse and PostToolUseFailure); 52 tests from recorded payloads; 6 mutants |
| A shell route the hooks never see (the PowerShell tool) | a probe: `git add -A` denied in Bash, run in PowerShell | matchers `Bash\|PowerShell`; `test_settings.py`; mutant |
| A failed command whose diagnostics are never scanned | a probe: an exit-3 command never reached the hook | `diagnostic_scan` on PostToolUseFailure; mutant |
| A guard that crashes, and so lets the call through | the transcript audit (a half-edited `guard_shared`) | crash handlers that refuse; tests on broken copies; 2 mutants |
| A commit gated on a filter's exit status (`pytest \| tail && git commit`) | the transcript audit | `guard_git`; mutant |
| `git` hidden behind a wrapper, an option or a `cd` | the probe tables (26 of 49 cases missed) | `guard_git`; 65 tests in `test_guard_git.py`; 11 `guard_git` mutants |
| A gate whose scope silently shrinks (pyrefly skipping `.claude/hooks`) | reading CI's output, not its exit code | `tools/check_types.py`; a planted error it must find; 2 mutants |
| A check that measures the working copy when it means to measure a copy | CI disagreeing with a local run | `tools/isolation.py`; `test_isolation.py` (RED under an editable install, as CI installs) |

The counts above, measured 2026-10-09:

```
$ pytest --collect-only -q tests/integration/test_diagnostic_scan.py | tail -1
52 tests collected in 0.03s
$ pytest --collect-only -q tests/integration/test_guard_git.py | tail -1
65 tests collected in 0.03s
$ python -c "from tools.mutation_check import MUTANTS; ..."   # mutants per file
.claude/hooks/diagnostic_scan.py 6
.claude/hooks/guard_git.py 11
.claude/hooks/guard_gates.py 7
.claude/hooks/post_edit_check.py 3
.claude/settings.json 2
```

"26 of 49" is the two `guard_git` probe rounds before the fixes: 17 of 29
and 9 of 20 mismatched (`docs/evidence/harness_probes_2026-10-09.md`).
