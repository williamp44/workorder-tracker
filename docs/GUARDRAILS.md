# Guardrails for AI-written code

This repo was written with an AI coding agent. The agent writes fluent code
that looks right to the thing that produced it, so care at the keyboard does
not catch its mistakes. What catches them is putting the work where being
wrong produces a visible disagreement: a test that goes red, a check that
fires, a database that refuses.

This page explains the method and each check in it. [CHECKS.md](CHECKS.md)
is the ledger: every defect found, which check found it, and the evidence.

## The method: oracle first

**Before writing code, decide how you will know it is correct.** That
decision is the *oracle*. It comes before the code, it is independent of the
code, and it has to be shown able to fail.

| Rule | Why | In this repo |
| --- | --- | --- |
| **State the oracle before the change.** | A result seen first gets rationalised. A result predicted first gets checked. | Every fix in `tests/test_review_findings.py` began as a failing test. The RED output is kept in `docs/evidence/`. |
| **The oracle must not be derived from the code under test.** | A test generated from the code shares the code's mistakes. | The transition spec in `tests/test_work_orders.py` is written out by hand. The first draft derived it from `ALLOWED_TRANSITIONS`, so a wrong table produced matching wrong tests that passed. |
| **Prove the oracle can fail.** | A check that has only ever been green has proved nothing. It may never reach the code. | `tools/mutation_check.py` injects 12 bugs. Each must turn the suite red. |
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

## The layers: prevent, catch in the turn, catch before merge

The earlier a defect is caught, the less is built on top of it.

### 1. Prevent: Claude Code hooks (`.claude/hooks/`, `.claude/settings.json`)

| Hook | When | What it does |
| --- | --- | --- |
| `guard_gates.py` | before any Write/Edit | Refuses edits to the gates themselves: the hooks, CI, the ruff and pyrefly configs, and the mutant list. An agent must not be able to loosen the check it is being judged by inside the same turn. |
| `guard_git.py` | before any Bash command | Refuses `git add -A`/`.`/a directory, and `git checkout --`/`git restore` over uncommitted work. In another project an agent ran both while the rules forbidding them were in its context. |

They judge a **path** or a **command**, facts in the payload that need no
understanding of the work. Hooks that tried to judge the work itself (is a
test failing, is this edit TDD-shaped) were measured in another project:
about 18 refusals and 0 defects caught. Those were not carried over.

**Tests are not gated.** Test-first means the agent writes tests. A test
weakened until it passes is caught by the mutation check: the mutant it used
to kill survives, and CI goes red.

**Limit:** Bash is not covered by `guard_gates`. A script can still write a
gate file. The hook moves weakening a gate from quiet to visible; it is not
a wall.

### 2. Catch in the turn: `post_edit_check.py`

After every edit to a Python file, ruff and pyrefly run on that file and any
findings go straight back to the agent (exit code 2) before it builds
anything else on top. It uses the same configuration CI gates on, so the
agent sees in the turn what CI would refuse.

Evidence: pyrefly caught 4 defects in code written during this work: a
function call used as a type annotation, a mistyped lookup table, a
`.rowcount` the declared type does not have, and an `Optional` used unchecked
(CHECKS.md).

### 3. Catch before merge: CI (`.github/workflows/ci.yml`)

| Step | Leg | Gate |
| --- | --- | --- |
| `ruff check .` | SQLite | zero findings |
| `pyrefly check` | SQLite | zero errors; the one suppression carries a reason |
| `pytest` | SQLite **and** MariaDB | all pass |
| `python tools/mutation_check.py` | SQLite | control passes, canary survives, every mutant killed |

### 4. Catch what checks cannot: review

Checks only answer questions somebody already asked. New defects came from
changing who is looking. A **Linus-style review** (taste, data structures,
needless special cases) and an **adversarial review** (try to break each
README claim, and prove it on a copy) found the status-change race, the CSRF
hole, and four smaller defects that every check had passed. Each is now a
test and, where it fits, a mutant, so the next regression is caught
mechanically.

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
