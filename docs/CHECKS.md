# Checks ledger

Every defect found in this repo, what found it, and the test that now holds
it. Every number has the command that produced it, so it can be re-run
rather than remembered. The method behind it is in
[GUARDRAILS.md](GUARDRAILS.md).

Measured 2026-10-09.

## Defects in the app

Each one was written as a failing test first (`tests/test_review_findings.py`;
RED output in `docs/evidence/review_findings_RED.txt`), then fixed.

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

## Measurements

### Mutation check

```
$ python tools/mutation_check.py
  control (no mutation)              pytest exit 0
  canary-docstring-only                pytest exit 0
  drop-tenant-filter-get-work-order    pytest exit 1
  drop-tenant-filter-list-work-orders  pytest exit 1
  drop-tenant-filter-get-site          pytest exit 1
  allow-done-to-open                   pytest exit 1
  unconditional-status-write           pytest exit 1
  snapshot-conflict-becomes-500        pytest exit 1
  drop-csrf-guard                      pytest exit 1
  accept-blank-names                   pytest exit 1
  unbounded-ids                        pytest exit 1
  gate-hook-forgets-ruff-config        pytest exit 1
  git-hook-allows-add-all              pytest exit 1
  migration-default-drifts-from-model  pytest exit 1
OK   control passed, equivalent canary survived, 12 of 12 mutants killed
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
