# Harness value assessments, 2026-10-10

Two read-only reviewer agents assessed the harness-hardening work. Their reports are recorded below as they
returned them, lightly formatted.

**Status: DRAFT analysis.** These are model-written reports. Claims marked VERIFIED cite a file, line or commit
the agent read. Claims marked INFERRED are its own judgement. Neither report has been re-checked line by line.
Notes added by the executing session are marked **[Note]**.

---

## Assessment 1: the value of the harness-hardening session

Scope: `main..harness-hardening` at `67718ee` (28 commits), `PRD_HARNESS_HARDENING.md`,
`progress_harness_hardening.txt`.

### Bottom line

- The session finished 17 of 18 PRD tasks and changed no app code, so it caught 0 app defects (VERIFIED).
- Every one of the ~16 defects it fixed was in the harness. About 7 of those were problems the harness, or its
  own process, had just created (VERIFIED).
- What earns its keep (INFERRED):
  - the gates that check outcomes: `check_red`, mutation, pytest, ruff;
  - the one new guard that refused a commit gated on a pipe filter.
- Guards that parse commands lose to an adversary: a fresh reviewer found ~30 bypasses straight after the work
  (VERIFIED).
- Recommendation (INFERRED): keep the outcome gates and a small set of guards against honest accidents. Stop
  closing parser holes row by row.

### 1. What was accomplished

**Done (VERIFIED):** US-001 to US-008, US-010 to US-014, and all three reviews.

**Skipped, blocked, changed:**
- US-009 was skipped by decision.
- US-015 Steps 1-2 are blocked: auto mode refused the probe hook edit.
- F1-F8 were fixed, and F9 (the docs) was regenerated.
- Two oracles changed and need a person's review: US-002 (an in-repo `.venv` masked the PRD's test) and US-013
  (it runs without a venv).

**Found, not fixed (VERIFIED):**
- the stale `.pyc` (R2-3)
- `guard_git` size (R2-2)
- ~30 fresh-reviewer bypasses (R3-2)
- the stash-drop rule
- R1-1 never seen firing without python3
- CI not run
- PRD Post-Build checkboxes unticked

**Size (VERIFIED):**
- 19 files changed, +3282/-160. Harness code and tests +1514/-135; PRD, progress and docs +1768/-25; `app/` 0 lines.
- Tests: 225 to 364. Mutants: 21 to 48, all 27 new ones targeting hooks or tools.

### 2a. App defects vs harness defects

- **App defects: 0.**
- **Harness defects:** 8 PRD findings, 7 found in-run (CHECKS rows 21-27), plus R3-1.
- **Self-checks:** rows 21-25 and R3-1 were the harness checking the harness.
- **Overall (INFERRED):** essentially all of the work is the harness checking the harness. That fits the PRD's
  charter, but it is still the cost.

### 2b. Did the guards change what the agent did?

**Real problem, real catch:**
- `guard_git` refused `pytest … | grep … && git commit`. A failing suite would have committed. This is the
  strongest win (VERIFIED).

**Real hazards, in the harness only:**
- the crashing guard failing open for ~18 s
- the stale `.pyc`

**Self-inflicted:**
- the `GATE_EDIT` leak into the tests (from P-1)
- the guard refusing its own author's commit (new `$( )` parsing)
- check_red judging HEAD, a process attribution error

**Misattributed in the agent's brief (VERIFIED):**
- `post_edit_check` did NOT catch the F401: the file had been written through Bash, and the ruff gate caught it.
- The type error it surfaced was a deliberate probe.
- **[Note]** The executing session wrote that wrong attribution into the brief. The agent corrected it.

**Marginal (INFERRED):** `check_fp` flagging the mutable `CHECKS` dict, a style catch.

### 2c. Ceremony with low payoff

- **Truncation warning:** 7 warned uses, 0 behaviour changes (retired).
- **Mutation check run time:** planned at ~2-3 min per run, now 13+ min, and run 17 times. That is 49 pytest
  runs, with the suite going from 8.5 s to 25 s.
- **Churn:** a mutant retargeted; US-007/US-008 split and re-applied; the prose diff larger than the code diff.
- **Scanner noise:** 4 false positives while the agent only read files.
  - **[Note]** Inflated: this repo's docs quote warnings on purpose.

### 2d. Cost

- **Time:** ~3.5 h wall time, against ~250 min estimated.
- **Size:** harness code and tests ~1.8× the estimated lines.
- **Commits:** 28 of 28 are harness or docs.
- **Maintenance:** `guard_git` is a 325-line hand-rolled Bash/PowerShell parser, with 65 tests and ~30 known
  holes.

### 2e. The ceiling

- **Command-parsing guards** are an open-ended blocklist: each row closes one spelling, and the attack surface is
  two shell languages (INFERRED).
- **Outcome gates** cannot be talked past by spelling.
- **Assurance per effort (INFERRED):**
  1. outcome gates and CI;
  2. a few cheap guards against honest mistakes;
  3. parser completeness, last.

### 3. Recommendation (INFERRED)

**Keep:**
- `check_red`, `mutation_check`, ruff, `check_types` and pytest in CI
- `guard_gates` with casefolded paths, and crash-refuses
- the core `guard_git` rules (add -A/., reset --hard, checkout/restore over dirty files, the pipe-gated commit)
- the PowerShell matchers, PostToolUseFailure scanning, and the SessionStart check

**Simplify:**
- Freeze `guard_git`'s table.
- Fix the stale `.pyc` with `python3 -B`.
  - **[Note]** Not enough on its own: the test suite also wrote `.pyc` files. Sprint 4's US-016 handles both.
- Run the mutation check in CI, or in parallel.

**Stop:**
- The ~30-row follow-up. Add only the cheap common rows:
  - abbreviated `--hard`/`--force`
  - `-qf` clusters
  - `git rm -f`
  - `..` in gate paths
- **[Note]** Those became Sprint 4, US-017 to US-019.

**Minimal harness:**
- CI: ruff, types, pytest, check_red, mutation.
- Hooks: `guard_gates`, a small `guard_git`, `post_edit_check`, the SessionStart check.
- `diagnostic_scan` is optional.

---

## Assessment 2: the repo as an incubator for tools copied into production codebases

Framing: the owner uses this repo to build and prove harness tools, which are then copied into production
codebases where AI coding agents do the work. Scope: the whole repo history.

### Bottom line

- **Worth transplanting, but only part of it.** It mostly prevents agent-process failures and guards itself; it
  does not find app defects.
- **App defects:** over the whole history, the harness's own tools found 1 of 11 (a latent one). Review and stock
  tools (ruff, pyrefly, a second database engine) found the other 10, including every serious one.
- **The incubator's real output:** ~13 silent defects in the instruments themselves, each of which would have
  given false assurance in production. That raises the value of the copyable parts.
- **Cost:** a few parts cost too much to copy as they are.

### 1. App defects found (CHECKS.md:16-28)

| Found by | App defects | Count |
| --- | --- | --- |
| Review only | #1 status race, #2 CSRF, #3 duplicate-name race, #4 id overflow, #5 blank names | 5 |
| Review first, then the mutation check confirmed it | #6 alembic ignoring server defaults | 1 |
| Stock tools, not the harness | #7, #8 (CI MariaDB leg); #9 (ruff); #10 (plain pyrefly) | 4 |
| A harness tool | #11 mutable constants (`check_fp`), a latent hazard | 1 |

- #10 landed in `393e8e2`, before any hook existed. `post_edit_check` could not start on Windows until `d8aae73`,
  so GUARDRAILS.md overstates the in-turn credit.
- **Hooks: 0. check_red: 0** (its history audit flagged only 2 unmarked controls).
- **Could the harness find these again elsewhere, unaided?** Only #11-type defects, and #6-type gaps if someone
  writes that mutant. Races, CSRF and overflow need adversarial review (INFERRED).

### 2. Transplant value

**(a) Project-agnostic:**
- `guard_git`
- the SessionStart python3 check
- `check_red` (any Python/pytest project)
- `isolation.py` (25 lines)
- the fail-closed crash handlers
- the equivalent canary inside `mutation_check`

**(b) Needs per-project setup (estimates INFERRED):**

| Tool | Setup per project |
| --- | --- |
| `guard_gates` | GATES list, ~30 min |
| `post_edit_check` | venv path and toolchain, ~1 h; Python only |
| `check_types` | pyrefly-specific, ~30 min |
| `check_fp` | `PURE_MODULES` and rules, 2-4 h with cleanup |
| `mutation_check` | ~15 min per hand-written mutant, re-targeted whenever code moves |
| `diagnostic_scan` | payload contract pinned per machine and harness version; ~1 h, plus recurring alarms |

**(c) Leave behind:** `complexity.py` (0 findings), `ruff_vs_mutants.py`, `check_discipline` (0 of 4, 2 false
positives).

### 3. Prevent vs find

**Prevent, all aimed at AI-agent failures (VERIFIED):**
- **`guard_git`.** Origin incident: an agent discarded an uncommitted fix while rules forbidding it were in
  context. It also refuses commits gated on `| tail` or `| grep`. Warnings changed behaviour 0 of 7 times;
  refusals changed it every time.
- **`guard_gates`.** The one judging hook that was "unambiguously right", against ~18 refusals and 0 defects for
  work-judging hooks elsewhere. It held live: Sprint 4 stopped instead of loosening a gate.
- **`check_red`.** It finds tests written after the code, but as a CI gate it acts as prevention.
- **`check_fp`.** It makes some states unrepresentable.

**Find only:**
- `mutation_check` (tests that cannot fail)
- `post_edit_check` and `check_types` (generic bugs)
- `diagnostic_scan` (the agent reading only the last line)

**Command parsing is an open-ended blocklist (VERIFIED):** ~30 fresh bypasses after hardening.

### 4. Cost

**Mutation run time:**
- It is serial, with a full copy and suite per mutant, so cost ≈ (mutants + 2) × suite time.
- Measured: harness tests 29 s, app tests 2.9 s, so ~90% of each mutant run tests the harness.
- ~34 of 47 mutants target the harness.
- At a 5-minute production suite, 30 mutants would take ~2.5 h (INFERRED).

**Noise:**
- precision probe: 0 hits on green gate output, but 3 of 51 files trip the scanner when merely read
- truncation warning: 7 warned uses, 0 changes
- contract false alarms: 6 in one session
- `guard_git` refusing its author's heredoc

**Fragility, recurring on every Windows project:**
- fail-open crashes
- the stale `.pyc`
- `python3` resolving to the Store stub
- the PowerShell matcher
- headless payload differences

These are fixed once, in the kit. What still recurs in every project: mutant upkeep, contract re-pinning,
blocklist growth.

### 5. The incubator's own return (VERIFIED, CHECKS.md:36-64)

Instrument defects that would have been silent and harmful in production:

| CHECKS # | Defect |
| --- | --- |
| 2 | the mutation self-test killed every mutant |
| 9 | the type gate never read the hooks |
| 10 | warnings above a `tail -1` |
| 13 | PowerShell bypassed every hook |
| 14 | `post_edit_check` never started on Windows |
| 16 | failed commands were never scanned |
| 17, 18 | probe gaps |
| 20 | pyrefly `ERROR` lines matched nothing |
| 24 | check_red judged HEAD |
| 25 | the stale `.pyc` |
| 26 | the fail-open crash |
| 27 | the commit gated on `tail` |

- #8 (editable install) was loud but wrong, the kind of failure that gets a gate switched off.
- **Count:** ~13 silent instrument defects, against 1 app defect found by the harness. This is the main product,
  and it is real.
- **Scale:** 55 commits, ~2,200 lines of harness code and ~1,750 of harness tests, for 543 lines of app.

### Transplant kit (INFERRED)

**Day one (~half a day):**
- `guard_git` as-is, plus `guard_shared`
- the SessionStart check, `python3 -B`, `Bash|PowerShell` matchers, crash-refuses
- `guard_gates` with the project's GATES list (30 min)
- `check_red` plus `isolation.py` in CI (1-2 h)
- ruff and the type checker in CI, with warnings failing the gate
- the suite on the production database engine

**Later (per project, ongoing):**
- `mutation_check` with the canary and 10-20 app-only mutants: ~15 min each, plus upkeep. Run the hook tests
  outside the mutant loop.
- `post_edit_check` (1 h)
- `check_fp`, only if the project adopts a functional core (2-4 h)
- `diagnostic_scan`, only after re-recording the contract and running a precision probe on that repo; drop the
  file-read patterns

**Leave behind:** `complexity.py`, `ruff_vs_mutants.py`, `check_discipline`, the hooks' own mutants and probe
history. Copy the hooks' tests, but gate them in the kit's repo, not in each project.

**Not a tool, but copy it:** a scheduled adversarial review that tries to break each claim. It found every
serious app defect.

---

## What the executing session did with these findings

- **Sprint 4** (US-016 to US-019) took the cheap rows and the stale-`.pyc` fix that Assessment 1 recommended, and
  nothing else from R3-2.
- **The ~25 other bypasses** stay recorded as limits in `harness_probes_2026-10-09.md`.
- **The transplant kit** is a recommendation. It is not built here.
