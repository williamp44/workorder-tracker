# Checks ledger

Every defect found in this repo, what found it, and the test that now holds
it. Every number has the command that produced it, so it can be re-run
rather than remembered. The method behind it is in
[GUARDRAILS.md](GUARDRAILS.md).

Measured 2026-10-09.

## Defects in the app

Each one was written as a failing test first (`tests/integration/test_review_findings.py`;
RED output in `docs/evidence/review_findings_RED.txt`), then fixed. That is
now checked from git history, not just claimed: see "RED first" below.

| # | Defect | Found by | Fix |
| --- | --- | --- | --- |
| 1 | Two concurrent status changes on one order: both pass the transition check and the last write wins, so `done` becomes `cancelled`, which the table forbids. Demonstrated live. | adversarial review; Linus review | The UPDATE only applies `WHERE status = <the status that was checked>`. Zero rows means 409. |
| 2 | The cookie-authenticated HTML POST accepted a cross-site form: 200 with only the cookie. Demonstrated live. | adversarial review | `/ui` POSTs require `HX-Request`; a cross-site form cannot set it without a CORS preflight. |
| 3 | Duplicate site name under a race: check-then-insert let the unique constraint raise, giving a 500. | Linus review; adversarial review | The unique constraint is the check; `IntegrityError` becomes 409. |
| 4 | `GET /api/work-orders/99999999999999999999` raised `OverflowError` (500). | adversarial review | Ids are bounded to the column's range (`1..2**31-1`); 422. |
| 5 | A site name or title of only spaces was accepted. | adversarial review | Names are trimmed and must be non-blank. |
| 6 | `alembic check` ignored server defaults, so a migration whose default drifted from the model passed. | adversarial review; then a mutant that survived | `compare_server_default`. |
| 7 | On MariaDB 11 the race in #1 surfaced as error 1020 ("Record has changed since last read"): a 500, not a 409. | CI, MariaDB leg | 1020 on the status UPDATE becomes 409. Any other database error still propagates (tested). |
| 8 | The fix for #6 reported a false difference on MariaDB, which reflects `now()` as `current_timestamp()`. A defect introduced by a fix. | CI, MariaDB leg | `app/schema_compare.py` treats every dialect's spelling of "now" as equal; anything else compares as written. |
| 9 | Error mapping duplicated in 5 routes; 7 × `raise` inside `except` without `from` (B904). | ruff; Linus review | One mapping in `app/main.py`; the try/except blocks are gone. |
| 10 | 4 type errors in code written during this work: a function call used as an annotation (×2), a lookup table whose key type did not match, `.rowcount` absent from the declared result type. | pyrefly | Typed aliases, an annotated table, an `isinstance` narrowing. |
| 11 | 7 mutable module constants, including the transition table itself (a dict of sets any importer could change) and the error-to-status map. | `check_fp` (`mutable-constant`), measured on `main` before the rule existed | tuples, frozensets, `MappingProxyType`; the transition decision moved to a pure `app/rules.py` |

## Defects in the instruments

An instrument built to check a claim is written by the same process that
made the claim, so it inherits blind spots. These were found in the checks
themselves.

| # | Defect | How it surfaced | Fix |
| --- | --- | --- | --- |
| 1 | `tools/ruff_vs_mutants.py` reported 3 findings on the tree; ruff reported 8. It stored findings in a set with line numbers dropped, so 7 identical messages collapsed to 2. | its number disagreed with a second source | a `Counter` |
| 2 | **The mutation check killed every mutant with its own self-test.** In a mutated copy, the test that every mutant still applies fails by construction, so all mutants looked killed whatever the app tests did. The first "4 of 4 killed" proved nothing. | a mutant was killed that the adversarial review had shown survives; asking *which test* killed it | mutant runs exclude the tool's own tests; an **equivalent canary** mutant that must survive now fails the run if anything but behaviour kills it. Shown to go red under the old command. |
| 3 | Two `# noqa: E402` waivers copied from another codebase suppressed nothing. | ruff `RUF100` | removed |
| 4 | `check_discipline` (15 AST rules from another codebase): 2 findings here, both false positives (`impure-decision` on the database layer, which is supposed to touch a cursor), and 0 of 4 mutants seen. | the two-number test | not adopted |
| 5 | A mock that patched a method the code no longer calls (`session.scalar`, after the pre-check was removed): the test still passed, so the patch was dead. | reviewing the tests against the no-mocks-in-unit-tests rule | removed; the test exercises the constraint directly |
| 6 | The first RED audit (a throwaway script) counted pre-existing tests as new, and one collection error aborted the run, so every test read as RED. Both overstated the result. | its numbers disagreed with what the commits contained | `tools/check_red.py` matches tests by file and id, and continues past collection errors |
| 7 | On its first run `check_red` failed 3 tests: two hook cases whose ids embedded a path that the unit/integration split had changed (the same tests, renamed), and a test that a *test fixture* was frozen, which only test code can make RED. | `check_red` itself | stable ids; the test of test code removed |
| 8 | **In CI, `check_red` reported 18 new tests as passing on the base code, for a module the base did not have.** CI installs the project editable (`pip install -e`), and setuptools' import finder served `app.rules` from the working copy to the base tree. The gate failed, but for the wrong reason: it had measured HEAD's code twice. Locally it passed, because the local venv had no editable install. | CI disagreeing with the local run, then reproducing it in a venv installed the way CI installs | `tools/isolation.py`: suites on copied trees run in a subprocess with the editable finders removed; used by `check_red` and the mutation check. `tests/integration/test_isolation.py` was RED under an editable install (`DID NOT RAISE ModuleNotFoundError`) and is green now. It can only go RED where the project is installed editable, which is how CI installs, so it has no mutant (a local mutation run could not kill one). |
| 9 | **The type gate never read the hooks.** pyrefly skips hidden directories whatever its excludes say, so `.claude/hooks` in `pyrefly.toml` was dropped with a one-line `WARN` and the gate still passed. Checked as explicit files, the hooks had 2 real warnings (redundant `str()` calls). A first fix then missed a planted error in a temp directory, because with no config in reach pyrefly falls back to a lenient preset. | reading CI's output instead of its exit code | `tools/check_types.py` checks the project and then the hooks as explicit files, with the preset pinned and warnings failing the gate. `test_check_types.py` plants an error in a hook and requires the command to find it; two mutants (hooks dropped, lenient preset) prove that test can fail. |
| 10 | **A warning printed and not read: the reader was the defect.** pyrefly's `WARN Skipping include pattern .claude/hooks` was printed above the summary line, locally and in CI. Locally the command was `pyrefly check 2>&1 | tail -1`, which kept only the last line. The failure is positional: diagnostics print first, at the top, and the reader, an AI agent here, scans the bottom for the verdict. | the user rereading CI's log | `.claude/hooks/diagnostic_scan.py`, ported from host6: a PostToolUse hook that scans every Bash result for unsolicited toolchain diagnostics, and the command for `2>&1 | tail` and heredoc hazards. Its findings are attached directly after the tool result in the same turn, where attention already is. 37 tests (`check_red --base 2b68ad6^ --head 2b68ad6` → `37 new test(s) ... OK all 37 new test(s) were RED`; the commit message said 35), built from a payload contract recorded live on host6; 2 mutants. |
| 11 | The FP gate caught 4 mutable module-level dicts in the guard's own new test file, on the first run after it was written. | `check_fp` (`mutable-constant`), immediately | `MappingProxyType`. The discipline applied to fresh code with no one remembering it. |
| 12 | One of the guard's suppressions, "`ok`/`FAIL` lines are the operator's own verdicts", is untested here: no verdict line this repo prints trips any pattern, so a mutant removing it survived. | the mutation check (a surviving mutant) | the suppression stays (it has evidence on host6); the mutant now targets git's line-ending advisory, the suppression that does matter here, since `warning: in the working copy...` matches the compiler-style pattern. |
| 13 | **F1. The PowerShell tool bypassed every shell hook**: the matchers named `Bash` only. | probe: `git add -A --dry-run` denied in Bash, exit 0 in PowerShell | matchers `Bash\|PowerShell` (`test_settings.py`). Live: PowerShell `git add -A --dry-run` → `PreToolUse:PowerShell hook error: \`git add -A\` ... stages everything` |
| 14 | **F2. `post_edit_check` could not start on Windows**: wired to `.venv/bin/python`. | the wired command: `exit=127 ... No such file or directory` | launched by `python3`; `venv_python(root, os_name)` picks the venv per OS; with no venv it exits 2 and says the layer is NOT running. Live: `x: int = "s"` → `ERROR \`Literal['s']\` is not assignable to \`int\` [bad-assignment]` in the same turn |
| 15 | **F3. False `missing-import` ERRORs** from `post_edit_check` and `check_types`: pyrefly asked the first python on PATH for site-packages. The PRD's first oracle (an empty PATH) passed on the base, because pyrefly auto-detects an in-repo `.venv`: `pyrefly dump-config` → `Using interpreter: ...\.venv\Scripts\python.exe`. | a probe on a clean file: 3 bogus ERRORs | `--python-interpreter-path`. The oracle is now a repo copy with no `.venv` and a bare venv first on PATH, RED on the base with `ERROR Cannot find module \`sqlalchemy\` [missing-import]` |
| 16 | **F4. A failed command was never scanned**: a non-zero exit fires `PostToolUseFailure`, not `PostToolUse`. Its payload, recorded live, carries the output in `error` and has no `tool_response`. | `.fired.log`: the exit-0 command logged, the exit-3 command not | registered on `PostToolUseFailure`; `payload_contract_failure.json`. Live: `echo "WARN live"; exit 3` → `the command FAILED (exit 3). Its output was scanned too: ... L2 WARN live` |
| 17 | **F5. `guard_git` missed discard and stage-all forms**, and denied `restore --staged` (index only). | `probe_git.py`: 17 of 29 mismatched; `probe_git2.py`: 9 of 20 | `test_guard_git.py` (65 tests). After: 1 and 1 mismatches, both explained in the evidence file's AFTER section |
| 18 | **F6. `guard_gates` missed gate files, case variants and NotebookEdit.** | `probe_gates.py`: 11 of 20 | the gate list, casefolded paths, `notebook_path`. After: `mismatches: 0` |
| 19 | **F7. Payload-contract false alarms**, 6 in one session, every one an added key (`persistedOutputPath`, `backgroundTaskId`, `bashEditDiff`, `returnCodeInterpretation`, ...). PowerShell's result also never has `noOutputExpected`. | the alarms, read live | only a lost key alarms; `noOutputExpected` is optional. Live: a persisted-output command and a background command → no contract note |
| 20 | **F8. pyrefly `ERROR` lines matched nothing**: 40+ in one output, 0 hits. | reading the output | the `^\s*ERROR\b` pattern; precision probe still 0 hits on all green gate output |
| 21 | The hook tests passed the session's env to the hooks, so in the session launched with `GATE_EDIT=1` the gate opened and the baseline went red: `1 failed, 224 passed`; mutation `control failed`. | the baseline run before US-001 | `run_hook` drops `GATE_EDIT` (aff6f44) |
| 22 | `post_edit_check` reported a false `Cannot find module guard_shared` on every hook edit, once it actually ran. | its own output, on the first hook edit | the hooks directory on pyrefly's search path for hook files |
| 23 | The new `$( )` parsing in `guard_git` refused its own author's commit: a heredoc body (the progress note) mentioned `$(git add -A)`. | the guard, live | `$( )` is looked for only outside heredoc bodies; test and mutant |
| 24 | **`check_red` judges the committed HEAD, not the working tree**, so each task's check_red line, run before its commit, covered the previous commits. | "107 new test(s)" both before and after new tests were added | gates now run on a clean worktree of each task's commit; the cumulative run covered every earlier test (81 of 81 RED) |
| 25 | A stale `.pyc` ran old hook code: a same-length edit within one second left the source mtime and size equal to the cache. | a test that should have passed did not, until `__pycache__` was removed | not fixed. Proposal: launch hooks with `python3 -B` (review issue R2-3) |
| 26 | A crashing PreToolUse hook exits 1, which lets the call through: a half-edited `guard_shared` switched every guard off for about 18 s. | the transcript audit | crash handlers that refuse, or, under `GATE_EDIT=1`, let the edit through and say so; tests on broken copies; 2 mutants |
| 27 | `pytest \| tail -2 && git commit` commits after a failing suite: the pipeline's status is `tail`'s. The `2>&1 \| tail` warning fired on such a call and changed nothing (7 warned uses, 0 changes). | the transcript audit | `guard_git` refuses the chain without `set -o pipefail`; the warning was retired. Live: `true \| tail -1 && git commit --dry-run` → `this commit is gated on tail's exit status` |
## CI evidence

The gates as they ran in GitHub Actions, not only locally: the command each
step ran and what it printed. Only per-test `PASSED` lines and environment
noise are trimmed. Each run is kept as the record of itself. The current
numbers are under Measurements, each with its command.

### Run 38086552299: PR 5 (harness hardening), commit `c4eec9a`, 2026-10-10

[CI run 38086552299](https://github.com/williamp44/workorder-tracker/actions/runs/38086552299),
`pull_request` event on [PR 5](https://github.com/williamp44/workorder-tracker/pull/5)
at `c4eec9a` (after Sprint 6), conclusion `success`. Both legs passed: SQLite
in 12m20s, MariaDB in 53s. Taken from `gh run view 38086552299 --log`.

This is the first Linux run of the tests written on Windows for
`PRD_HARNESS_HARDENING.md`. None of them assumed Windows. CI also killed
`test-helpers-write-bytecode`, which survives locally whenever a shell sets
`PYTHONDONTWRITEBYTECODE=1`.

Trimmed as environment noise from the runner, not this repo: a Node
`DeprecationWarning` for `punycode` during GitHub's post-job cleanup, and
MariaDB 11.8's `io_uring_queue_init() failed with EPERM ... falling back to
libaio` in the service container's log.

**Lint (ruff)** (SQLite leg)

```
$ ruff check .
All checks passed!
```

**Types (pyrefly, project and hooks)** (SQLite leg)

```
$ python -m tools.check_types
 INFO Checking project configured at `/home/runner/work/workorder-tracker/workorder-tracker/pyrefly.toml`
 INFO 0 diagnostics (4 suppressed)
 INFO 0 diagnostics
```

The second line is the project and the third the hooks, checked as explicit
files. The `WARN Skipping include pattern .../.claude/hooks` that run
37980856090 printed (instrument defect 9) is gone.

**Test (SQLite)** (SQLite leg)

```
$ pytest -v
collecting ... collected 409 items
============================= 409 passed in 15.46s =============================
```

**FP discipline (check_fp)** (SQLite leg)

```
$ python -m tools.check_fp
0 finding(s)
```

**RED first (check_red)** (SQLite leg)

```
$ python -m tools.check_red --base origin/main
  base 8209a76f  head HEAD
  198 new test(s), 49 declared control(s)
OK   all 149 new test(s) were RED on the base code
```

**Mutation check (SQLite)** (SQLite leg)

```
$ python -m tools.mutation_check
  control (no mutation)              pytest exit 0
  canary-docstring-only                pytest exit 0
  drop-tenant-filter-get-work-order    pytest exit 1
  drop-tenant-filter-list-work-orders  pytest exit 1
  drop-tenant-filter-get-site          pytest exit 1
  allow-done-to-open                   pytest exit 1
  transition-table-made-mutable        pytest exit 1
  rules-core-does-io                   pytest exit 1
  unit-test-uses-a-mock                pytest exit 1
  unconditional-status-write           pytest exit 1
  snapshot-conflict-becomes-500        pytest exit 1
  drop-csrf-guard                      pytest exit 1
  accept-blank-names                   pytest exit 1
  unbounded-ids                        pytest exit 1
  red-gate-accepts-green-tests         pytest exit 1
  fp-check-allows-mutable-constants    pytest exit 1
  type-check-skips-the-hooks           pytest exit 1
  type-check-on-lenient-preset         pytest exit 1
  diagnostic-guard-reads-the-documented-key pytest exit 1
  diagnostic-guard-fires-on-git-advisory pytest exit 1
  gate-hook-forgets-ruff-config        pytest exit 1
  gate-hook-forgets-settings-local     pytest exit 1
  gate-override-accepts-any-value      pytest exit 1
  shell-hooks-skip-powershell          pytest exit 1
  hooks-write-bytecode                 pytest exit 1
  test-helpers-write-bytecode          pytest exit 1
  gate-hook-skips-notebooks            pytest exit 1
  post-edit-drops-interpreter-path     pytest exit 1
  check-types-drops-interpreter-path   pytest exit 1
  scan-ignores-failed-commands         pytest exit 1
  python3-check-silent                 pytest exit 1
  gates-case-sensitive                 pytest exit 1
  gates-skip-dotdot                    pytest exit 1
  gates-forget-check-red               pytest exit 1
  post-edit-forgets-hook-siblings      pytest exit 1
  git-hook-ignores-global-options      pytest exit 1
  git-hook-ignores-nested-shell        pytest exit 1
  git-hook-runs-heredoc-subshells      pytest exit 1
  git-hook-allows-checkout-without-dashdash pytest exit 1
  git-hook-allows-reset-hard           pytest exit 1
  git-hook-allows-rm-force             pytest exit 1
  git-hook-misses-abbreviated-options  pytest exit 1
  git-hook-misses-f-in-cluster         pytest exit 1
  git-hook-ignores-cd                  pytest exit 1
  git-hook-ignores-repo-aliases        pytest exit 1
  git-hook-denies-index-only-restore   pytest exit 1
  git-hook-crash-fails-open            pytest exit 1
  gate-hook-crash-blocks-override      pytest exit 1
  post-edit-judges-outside-files       pytest exit 1
  shell-written-python-unchecked       pytest exit 1
  shell-check-ignores-git-state        pytest exit 1
  shell-check-misses-same-command-commit pytest exit 1
  shell-check-hides-unchecked-names    pytest exit 1
  commit-gated-on-filter-allowed       pytest exit 1
  contract-alarms-on-added-keys        pytest exit 1
  scan-misses-pyrefly-error            pytest exit 1
  contract-alarms-on-headless-sessions pytest exit 1
  git-hook-allows-add-all              pytest exit 1
  migration-default-drifts-from-model  pytest exit 1
OK   control passed, equivalent canary survived, 57 of 57 mutants killed
```

**Test (MariaDB)** (MariaDB leg)

```
$ pytest -v
collecting ... collected 409 items
============================= 409 passed in 17.21s =============================
```

### Run 37980856090: PR #2, commit `360bf79`

[CI run 37980856090](https://github.com/williamp44/workorder-tracker/actions/runs/37980856090),
on PR #2's last commit `360bf79`, merged into `main` as `6d31252`
(174 tests, 17 mutants).

**Lint (ruff)** (SQLite leg)

```
$ ruff check .
All checks passed!
```

**Types (pyrefly)** (SQLite leg)

```
$ pyrefly check
 INFO Checking project configured at `./pyrefly.toml`
 WARN Skipping include pattern `./.claude/hooks` because it is matched by `project-excludes` or an ignore file.
`project-excludes`: [**/node_modules, **/__pycache__, **/venv/**/*, /opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages], ignore files [./.g...
 INFO 0 errors (4 suppressed)
```

**FP discipline (check_fp)** (SQLite leg)

```
$ python -m tools.check_fp
0 finding(s)
```

**Test (SQLite)** (SQLite leg)

```
$ pytest -v
collecting ... collected 174 items
============================= 174 passed in 2.61s ==============================
```

**Test (MariaDB)** (MariaDB leg)

```
$ pytest -v
collecting ... collected 174 items
============================= 174 passed in 3.92s ==============================
```

**RED first (check_red)** (SQLite leg)

```
$ python -m tools.check_red --base origin/main
  base 7e45b323  head HEAD
  72 new test(s), 1 declared control(s)
OK   all 71 new test(s) were RED on the base code
```

**Mutation check (SQLite)** (SQLite leg)

```
$ python -m tools.mutation_check
  control (no mutation)              pytest exit 0
  canary-docstring-only                pytest exit 0
  drop-tenant-filter-get-work-order    pytest exit 1
  drop-tenant-filter-list-work-orders  pytest exit 1
  drop-tenant-filter-get-site          pytest exit 1
  allow-done-to-open                   pytest exit 1
  transition-table-made-mutable        pytest exit 1
  rules-core-does-io                   pytest exit 1
  unit-test-uses-a-mock                pytest exit 1
  unconditional-status-write           pytest exit 1
  snapshot-conflict-becomes-500        pytest exit 1
  drop-csrf-guard                      pytest exit 1
  accept-blank-names                   pytest exit 1
  unbounded-ids                        pytest exit 1
  red-gate-accepts-green-tests         pytest exit 1
  fp-check-allows-mutable-constants    pytest exit 1
  gate-hook-forgets-ruff-config        pytest exit 1
  git-hook-allows-add-all              pytest exit 1
  migration-default-drifts-from-model  pytest exit 1
OK   control passed, equivalent canary survived, 17 of 17 mutants killed
```

**What this output was worth beyond the green.** The pyrefly step printed a
`WARN Skipping include pattern .../.claude/hooks` and still passed: the type
gate had never read a single hook. That is instrument defect 9 below, found
by reading the output rather than the exit code. CI now runs
`python -m tools.check_types`, which checks the hooks as explicit files.

The run before this one failed in `check_red`, correctly but for the wrong
reason (instrument defect 8): CI's editable install let the base tree import
the working copy's code.

## Measurements

### Mutation check

At `8d8fc99` (US-008), on a clean worktree of that commit:

```
$ python -m tools.mutation_check
  control (no mutation)              pytest exit 0
  canary-docstring-only                pytest exit 0
  drop-tenant-filter-get-work-order    pytest exit 1
  drop-tenant-filter-list-work-orders  pytest exit 1
  drop-tenant-filter-get-site          pytest exit 1
  allow-done-to-open                   pytest exit 1
  transition-table-made-mutable        pytest exit 1
  rules-core-does-io                   pytest exit 1
  unit-test-uses-a-mock                pytest exit 1
  unconditional-status-write           pytest exit 1
  snapshot-conflict-becomes-500        pytest exit 1
  drop-csrf-guard                      pytest exit 1
  accept-blank-names                   pytest exit 1
  unbounded-ids                        pytest exit 1
  red-gate-accepts-green-tests         pytest exit 1
  fp-check-allows-mutable-constants    pytest exit 1
  type-check-skips-the-hooks           pytest exit 1
  type-check-on-lenient-preset         pytest exit 1
  diagnostic-guard-reads-the-documented-key pytest exit 1
  diagnostic-guard-fires-on-git-advisory pytest exit 1
  gate-hook-forgets-ruff-config        pytest exit 1
  gate-hook-forgets-settings-local     pytest exit 1
  gate-override-accepts-any-value      pytest exit 1
  shell-hooks-skip-powershell          pytest exit 1
  gate-hook-skips-notebooks            pytest exit 1
  post-edit-drops-interpreter-path     pytest exit 1
  check-types-drops-interpreter-path   pytest exit 1
  scan-ignores-failed-commands         pytest exit 1
  python3-check-silent                 pytest exit 1
  gates-case-sensitive                 pytest exit 1
  gates-forget-check-red               pytest exit 1
  post-edit-forgets-hook-siblings      pytest exit 1
  git-hook-ignores-global-options      pytest exit 1
  git-hook-ignores-nested-shell        pytest exit 1
  git-hook-runs-heredoc-subshells      pytest exit 1
  git-hook-allows-checkout-without-dashdash pytest exit 1
  git-hook-allows-reset-hard           pytest exit 1
  git-hook-ignores-cd                  pytest exit 1
  git-hook-ignores-repo-aliases        pytest exit 1
  git-hook-denies-index-only-restore   pytest exit 1
  git-hook-crash-fails-open            pytest exit 1
  gate-hook-crash-blocks-override      pytest exit 1
  post-edit-judges-outside-files       pytest exit 1
  shell-written-python-unchecked       pytest exit 1
  commit-gated-on-filter-allowed       pytest exit 1
  contract-alarms-on-added-keys        pytest exit 1
  scan-misses-pyrefly-error            pytest exit 1
  git-hook-allows-add-all              pytest exit 1
  migration-default-drifts-from-model  pytest exit 1
OK   control passed, equivalent canary survived, 47 of 47 mutants killed
```

### Tests

```
$ pytest -q
362 passed in 25.22s
```

The verdict reads pytest's exit code, never its output. Exit 1 means tests
failed; exits 2-5 mean pytest could not run, which counts as inconclusive,
not killed. Each mutant applies to a temp copy; the working tree is never
touched.

### ruff: does a generic linter see the tenant bugs?

```
$ python -m tools.ruff_vs_mutants          # measured on the first 4 mutants
  drop-tenant-filter-get-work-order    +1  app/services.py:ARG001 Unused function argument: `tenant_id`
  drop-tenant-filter-list-work-orders  +1  app/services.py:ARG001 Unused function argument: `tenant_id`
  drop-tenant-filter-get-site          +1  app/services.py:ARG001 Unused function argument: `tenant_id`
  allow-done-to-open                   +0
```

3 of 4, and only because of a design rule: every service function takes
`tenant_id`, so dropping its filter leaves the argument unused. If
`tenant_id` were also read for logging, ARG001 would go quiet. Before tuning,
ruff reported 29 findings: 18 were FastAPI's `Depends(...)` idiom (tuned out
via `extend-immutable-calls`), 3 were Alembic's required import order
(per-file ignore), and 8 were real (#9 above and an unused fixture argument).
Now 0.

### pyrefly

The config file is load-bearing. Without one, pyrefly falls back to a
lenient preset that reports nothing on a `None` passed to a `str` parameter.
So the first run planted exactly that as a control:

```
ERROR Argument `None` is not assignable to parameter `x` with type `str` in function `f` [bad-argument-type]
 --> tools/zz_control.py:4:3
```

Then it was removed. Now 0 errors, plus 1 suppression with its reason inline
(Jinja's stubs type `env.globals` as built-ins only).

### Complexity (a report, not a gate)

```
$ python -m tools.complexity
  0 function(s) over 100 lines or deeper than 5
```

### RED first (`tools/check_red.py`)

Every new test must fail against the code before the change. This branch
against `main`:

```
$ python -m tools.check_red --base main      # branch harness-hardening at 8d8fc99
  base 8209a76f  head HEAD
  151 new test(s), 34 declared control(s)
OK   all 117 new test(s) were RED on the base code
```

The same tool, run over the earlier commits:

```
$ python -m tools.check_red --base 2723cd8^ --head 2723cd8
  11 new test(s), 0 declared control(s)
OK   all 11 new test(s) were RED on the base code
$ python -m tools.check_red --base 393e8e2^ --head 393e8e2
  21 new test(s), 0 declared control(s)
FAIL test_review_findings::test_ui_status_post_from_htmx_with_cookie_still_works passed before the change
$ python -m tools.check_red --base fb28feb^ --head fb28feb
  42 new test(s), 0 declared control(s)
FAIL test_review_findings::test_other_database_errors_are_not_disguised_as_conflicts passed before the change
```

The two failures are controls: tests written to pin behaviour that must
*keep* working (the legitimate HTMX path; database errors other than 1020
still propagating). Those commits predate the `control` marker, so they
could not say so; both now carry it with a reason. Every other new test in
the project's history was RED first: 11 of 11, 20 of 21, 41 of 42.

The original two commits (the app as first written) predate any of this
and cannot be audited: the code and its tests arrived in one commit.

### Functional discipline (`tools/check_fp.py`)

| | findings |
| --- | --- |
| `main` before this rule existed | 7, all `mutable-constant` (transition table, error-status map, `NOW`, `SCAN`, `MUTANTS`, two test tables) |
| now | 0 |

Each rule is shown firing on its target shape and quiet on the nearest
correct one (`tests/unit/test_fp_discipline.py`), and three mutants prove
the suite fails when the core is broken: a mutable transition table, an I/O
import in `app/rules.py`, and a mock in a unit test.

### Mocks

All substitutions are in `tests/integration/test_review_findings.py`, where
they stage what a real collaborator cannot do on demand: a second request
landing between a read and a write, MariaDB's 1020 error on SQLite, a lost
connection. `tests/unit/` has none, and `check_fp` keeps it that way.
