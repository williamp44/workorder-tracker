# Work-Order Tracker

A small multi-tenant work-order service: operators track service jobs (restocks,
repairs, card-reader faults) across their sites. Each tenant sees only its own data.

**Stack:** Python · FastAPI · async SQLAlchemy 2 · Alembic · MariaDB · HTMX + Jinja + Tailwind · pytest · GitHub Actions

## What it shows

The domain is deliberately small. The point is how it handles **multi-tenant data safely**:

| Concern | How it's handled |
| --- | --- |
| Tenant identity | API key in `X-API-Key` header (or cookie for the HTML page). Only a SHA-256 hash is stored. |
| Query scoping | Every function in `app/services.py` takes `tenant_id` and filters on it. Nothing queries tenant rows without one. |
| ID probing | Another tenant's row returns **404, not 403**, so a caller can't learn that an ID exists. |
| Defense in depth | A composite foreign key `(site_id, tenant_id) → sites(id, tenant_id)` makes the **database** reject a work order pointing at another tenant's site, even if application code has a bug. |
| State changes | Status moves through an explicit transition table (`open → in_progress → done`, plus cancel / reopen); anything else is a 409. |
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

CI runs the suite twice on every push and PR: once on SQLite, once against a MariaDB 11 service container.

### Tests are checked for teeth

A passing suite only matters if it fails when the code is wrong. Each of these deliberate bugs was introduced into `app/services.py`, confirmed to fail the suite, then reverted:

| Injected bug | Caught by |
| --- | --- |
| Drop `tenant_id` filter from single work-order lookup | 3 tests |
| Drop `tenant_id` filter from work-order list | 2 tests |
| Drop `tenant_id` filter from site lookup | 1 test (cross-tenant create) |
| Allow `done → open` | 2 tests |

The last row found a flaw in the first draft of the tests. The transition cases were *generated from* the transition table they were testing, so a wrong table produced matching wrong tests that still passed. The expected transitions are now written out independently in the test file.

## Layout

```
app/
  main.py          FastAPI app
  db.py            async engine/session (SQLite FK pragma on)
  models.py        Tenant, Site, WorkOrder (+ composite tenant FK)
  tenancy.py       API key → Tenant dependency
  services.py      all tenant-scoped data access + transition rules
  routers/api.py   JSON API
  routers/ui.py    HTMX page + row partial
  templates/       Jinja
alembic/           migrations (hand-written, dialect-neutral)
tests/             tenant isolation, transitions, UI partials, migrations
scripts/           tenant creation, MariaDB init
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
