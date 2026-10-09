# Checks: what each one can see, measured

Every check in this repo had to show two numbers before it was allowed to
gate CI:

1. **Does it fire on the defect?** Run against the known bugs (the mutants in
   `tools/mutation_check.py`).
2. **Is it quiet on the current tree?** Or, if it is not, what is each finding?

A check that is quiet on the tree but blind to the defects is decoration. A
check that fires on the defects but is noisy on the tree gets switched off
within a week. Each entry records the command and its output, so a number can
be re-run rather than remembered.

---

## Mutation check (`tools/mutation_check.py`), 2026-10-09

The suite must fail when the code is wrong. Each mutant is applied to a temp
copy of the repo, never the working tree; an unmutated copy runs first as a
control and must pass.

```
$ python tools/mutation_check.py
  control (no mutation)              pytest exit 0
  drop-tenant-filter-get-work-order    pytest exit 1
  drop-tenant-filter-list-work-orders  pytest exit 1
  drop-tenant-filter-get-site          pytest exit 1
  allow-done-to-open                   pytest exit 1
OK   control passed, 4 of 4 mutants killed
exit=0
```

**Proved it can fail.** A first green proves nothing until the check has been
seen red. A canary mutant that only edits a docstring (which no test can or
should catch) was added for one run:

```
  canary-docstring-only                pytest exit 0
FAIL canary-docstring-only survived: the suite passed with the bug in place
exit=1
```

**The check is code, so it has tests** (`tests/test_mutation_check.py`, 11
tests, written first and seen failing). They pin the three ways a mutation
tool lies:

- a pattern that no longer matches makes the "mutant" the unchanged code, so
  it survives and blames the tests: `apply` refuses zero or several matches;
- a red control makes every mutant look killed: the verdict fails on it;
- pytest exit 2-5 means the suite never ran: counted as inconclusive, not
  killed.

---

## ruff (`ruff.toml`), 2026-10-09

The rule families were carried over from a larger codebase where each one
had caught a real defect. Before tuning, on this tree:

```
$ ruff check --statistics .
18  B008    function-call-in-default-argument
 7  B904    raise-without-from-inside-except
 3  E402    module-import-not-at-top-of-file
 1  ARG001  unused-function-argument
Found 29 errors.
```

| finding | n | verdict | action |
| --- | --- | --- | --- |
| B008 on `Depends(...)` / `Form(...)` | 18 | FastAPI's idiom, 0 real | `extend-immutable-calls`; tuned, not waived |
| E402 in `alembic/env.py` | 3 | the sys.path-then-import shape Alembic needs | per-file ignore |
| B904 in `app/routers/` | 7 | real: raising `HTTPException` inside `except` without `from` chains an internal exception into the traceback | **open**: fix pending review |
| ARG001 in `tests/test_tenant_isolation.py` | 1 | fixture requested for its side effect, not its value | **open**: fix pending review |

After tuning: 8 findings, all real, all open.

**Does it fire on the defects?** Measured with `tools/ruff_vs_mutants.py`:

```
$ python -m tools.ruff_vs_mutants
  current tree: 8 finding(s)
  drop-tenant-filter-get-work-order    +1  app/services.py:ARG001 Unused function argument: `tenant_id`
  drop-tenant-filter-list-work-orders  +1  app/services.py:ARG001 Unused function argument: `tenant_id`
  drop-tenant-filter-get-site          +1  app/services.py:ARG001 Unused function argument: `tenant_id`
  allow-done-to-open                   +0
  ruff adds a finding on 3 of 4 mutants
```

**A generic linter catches 3 of the 4 tenant-isolation bugs**, and only
because of a design rule: every function in `app/services.py` takes
`tenant_id`, so dropping its filter leaves the argument unused. The protection
is conditional. If `tenant_id` were also read for logging, ARG001 would go
quiet and only the tests would remain. It sees nothing in the transition
table, which is data, not code.

**The measurement tool had a defect of its own, found on its first run.** It
first reported `current tree: 3 finding(s)` against ruff's 8. Findings were
stored in a set with line numbers dropped, so seven identical B904 messages
collapsed to two. Now a `Counter`. The number disagreeing with a second source
is what exposed it.

---

## Complexity report (`tools/complexity.py`), 2026-10-09

A report, not a gate: it says where to read closely.

```
$ python -m tools.complexity --stats
  79 functions in app, scripts, tools, tests, alembic
  median 8 lines, longest 47, median depth 0
          0-30 lines:   78
        31-100 lines:    1
      over 100 lines:    0
$ python -m tools.complexity
  0 function(s) over 100 lines or deeper than 5
```

Nothing to report on a repo this size, which is the expected result.
