# Work-Order Tracker

A small multi-tenant work-order service: operators track service jobs (restocks,
repairs, card-reader faults) across their sites. Each tenant sees only its own data.

It was built with an AI coding agent, inside guardrails that enforce the rules
with tools rather than trusting the agent to follow them: oracles written
before the code, a gate that requires every new test to fail before the change
(RED first), a mutation check that proves the tests can fail, a functional core
with immutable data checked by an AST rule set, lint and type gates that report
in the same turn as the edit, and hooks that stop the agent from loosening the
checks it is judged by. Each new class of defect found becomes a new check. **[docs/GUARDRAILS.md](docs/GUARDRAILS.md)** explains
the method; **[docs/CHECKS.md](docs/CHECKS.md)** logs every defect the checks
and reviews found, and how each was fixed.

**Stack:** Python · FastAPI · async SQLAlchemy 2 · Alembic · MariaDB · HTMX + Jinja + Tailwind · pytest · GitHub Actions

## What it shows

The domain is deliberately small. The point is how it handles **multi-tenant data safely** and the **harness engineering guardrails** included to prevent and find defects in AI-generated code (see [docs/GUARDRAILS.md](docs/GUARDRAILS.md)). The multi-tenant handling:

| Concern | How it's handled |
| --- | --- |
| Tenant identity | API key in `X-API-Key` header (or cookie for the HTML page). Only a SHA-256 hash is stored. |
| Query scoping | Every function in `app/services.py` takes `tenant_id` and filters on it. Nothing queries tenant rows without one. |
| ID probing | Another tenant's row returns **404, not 403**, so a caller can't learn that an ID exists. |
| Defense in depth | A composite foreign key `(site_id, tenant_id) → sites(id, tenant_id)` makes the **database** reject a work order pointing at another tenant's site, even if application code has a bug. |
| State changes | Status moves through an explicit transition table (`open → in_progress → done`, plus cancel / reopen); anything else is a 409. The write is conditional on the status that was checked, so two concurrent requests cannot slip `done → cancelled` past the table. |
| CSRF | The HTML page authenticates by cookie, so its POSTs require the `HX-Request` header, which a cross-site form cannot send. |
| Schema drift | A test runs `alembic upgrade`, `alembic check` (models must match migrations exactly), then downgrade/upgrade round-trip. |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Option A: SQLite, zero setup
alembic upgrade head
python -m scripts.create_tenant "Acme Vending" --demo   # prints an API key once
uvicorn app.main:app --reload

# Option B: MariaDB
docker compose up -d
export DATABASE_URL="mysql+aiomysql://app:app@127.0.0.1:3306/workorders"
alembic upgrade head
python -m scripts.create_tenant "Acme Vending" --demo
uvicorn app.main:app --reload
```

API docs: http://127.0.0.1:8000/docs. For the HTML page, set an `api_key` cookie to your key and open http://127.0.0.1:8000/. The status buttons update one table row in place over HTMX.

## Test it

```bash
pytest                                   # in-memory SQLite, ~2s

# Same suite against real MariaDB (docker compose creates workorders_test):
TEST_DATABASE_URL="mysql+aiomysql://app:app@127.0.0.1:3306/workorders_test" pytest
```

CI runs on every push and PR: ruff, pyrefly, the functional-discipline check, the suite on SQLite, the suite again against a MariaDB 11 service container, the mutation check, and on pull requests the RED-first gate.

```bash
ruff check .                              # lint, zero findings
python -m tools.check_types              # types: the project, and the hooks pyrefly would skip
python -m tools.check_fp                  # immutable constants, pure core, no mocks in unit tests
python -m tools.mutation_check            # prove the suite fails when the code is wrong
python -m tools.check_red --base main     # every new test fails on main's code
```

`tests/unit/` is pure and never mocks; `tests/integration/` uses the database and may substitute a collaborator.

### Tests are checked for teeth

A passing suite only matters if it fails when the code is wrong. `tools/mutation_check.py` injects each of these bugs into a temporary copy of the repo and requires the suite to fail:

| Injected bug | Guards |
| --- | --- |
| Drop the `tenant_id` filter from the work-order lookup, the work-order list, or the site lookup (3 mutants) | tenant isolation |
| Allow `done → open`; make the transition table mutable; give the pure core an I/O import | the transition rules and the functional core |
| Write the status unconditionally | the race fix |
| Treat MariaDB's snapshot conflict (1020) as an ordinary error | the race fix on MariaDB 11 |
| Drop the `HX-Request` requirement | CSRF |
| Accept blank names; accept ids beyond the column range | input validation |
| Let the migration's server default drift from the model | `alembic check` |
| Let `guard_gates` forget a gate; let `guard_git` allow `git add -A` | the hooks |
| Let `check_red` accept a green new test; let `check_fp` accept a mutable constant; put a mock in a unit test | the discipline checks themselves |

An unmutated copy must pass first, and an **equivalent** mutant that changes only a docstring must *survive*. If it is killed, something other than behaviour is failing the suite, and the run fails. That canary exists because the mutation check once killed every mutant with its own self-test (see [CHECKS.md](docs/CHECKS.md)).

The transition tests carry the oldest lesson here. Their first draft *generated* the expected transitions from the table under test, so a wrong table produced matching wrong tests that passed. The expected transitions are now written out independently.

## Layout

```
app/
  main.py          FastAPI app
  db.py            async engine/session (SQLite FK pragma on)
  models.py        Tenant, Site, WorkOrder (+ composite tenant FK)
  tenancy.py       API key → Tenant dependency
  rules.py         the functional core: transition rules, pure and immutable
  services.py      the imperative shell: tenant-scoped data access
  routers/api.py   JSON API
  routers/ui.py    HTMX page + row partial
  templates/       Jinja
  schema_compare.py server-default comparison for alembic check
alembic/           migrations (hand-written, dialect-neutral)
tests/unit/        pure tests, no database, no mocks
tests/integration/ tenant isolation, transitions, UI, migrations, review findings, hooks
tests/spec.py      the hand-written transition spec (the oracle)
scripts/           tenant creation, MariaDB init
tools/             check_red, check_fp, mutation check, ruff-vs-mutants, complexity report
docs/              GUARDRAILS.md (method), CHECKS.md (defect ledger)
.claude/           agent hooks: guard_gates, guard_git, post_edit_check
```

## API

| Method | Path | |
| --- | --- | --- |
| POST | `/api/sites` | create site |
| GET | `/api/sites` | list sites |
| POST | `/api/work-orders` | create work order (site must be yours) |
| GET | `/api/work-orders?status_filter=open` | list, optionally by status |
| GET | `/api/work-orders/{id}` | fetch one |
| PATCH | `/api/work-orders/{id}/status` | change status (validated) |
