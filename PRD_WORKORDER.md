---
name: workorder-tracker
description: Multi-tenant work-order tracker (FastAPI, async SQLAlchemy, Alembic, MariaDB, HTMX), built test-first
version: 1.0.0
complexity: medium
estimated_build_time: 150 min
estimated_tasks: 16
prerequisites:
  tools: [Claude Code CLI, Python 3.11+, git, Docker]
  services: [MariaDB 11 via docker compose]
  optional: [GitHub CLI (gh) for pushing and watching CI]
categories: [python, fastapi, multi-tenant, tdd]
execution:
  engines: [ralph.sh, ralphonce.sh]
  default: ralph.sh
  model: sonnet
tested_on: [Ubuntu 24.04, MariaDB 10.11 and 11]
repository: github.com/williamp44/{{REPO_NAME}}
---

# PRD: Work-Order Tracker - Multi-Tenant FastAPI Code Sample

## Introduction

A small service where operators track work orders (restocks, repairs, card-reader faults) across their sites. The domain is intentionally small. The value is in **safe multi-tenant data handling**, **test-first development**, and a stack that matches FastAPI / async SQLAlchemy / Alembic / MariaDB / HTMX shops.

A finished **reference implementation** accompanies this PRD (`workorder-tracker/`, 29 tests, green on SQLite and MariaDB). Use it as an **oracle**: build from this PRD in a fresh directory, then diff behavior and test results against the reference. Disagreements are findings for the defect ledger. Do not copy files across.

## Goals

1. Every tenant-owned query is scoped by `tenant_id`; cross-tenant access returns 404.
2. The database itself rejects cross-tenant references (composite FK), not just the app.
3. Alembic migrations are proven to match the models (`alembic check` in a test) and to round-trip.
4. The same pytest suite passes on SQLite (fast, local) and MariaDB (CI).
5. Tests are proven to have teeth: injected bugs make them fail.

## User Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `{{REPO_NAME}}` | `workorder-tracker` | GitHub repo name |
| `{{PROJECT_DIR}}` | `~/code/workorder-tracker` | Build directory (NOT the reference copy) |
| `{{REFERENCE_DIR}}` | `~/code/workorder-tracker-reference` | Unzipped reference implementation, read-only |
| `{{PYTHON}}` | `python3.12` | Interpreter for the venv |

### How to Build

```bash
./scripts/ralphonce.sh workorder sonnet        # US-000 only; check setup
./scripts/ralph.sh workorder 20 2 sonnet       # remaining tasks unattended
```

## Task Summary

- **Total:** 13 build tasks + 3 review gates = 16
- **Progress:** 0/16 complete (0%)
- **Status:** Not started
- **Next Task:** US-000

## Task Dependencies

```mermaid
graph TD
  US000[US-000 Bootstrap] --> US001[US-001 Models + DB]
  US001 --> US002[US-002 Alembic + migration test]
  US001 --> US003[US-003 Tenancy + API keys]
  US002 --> RS1{US-REVIEW-S1}
  US003 --> RS1
  RS1 --> US004[US-004 Sites API]
  US004 --> US005[US-005 Work orders + isolation]
  US005 --> US006[US-006 Status transitions]
  US005 --> US007[US-007 Composite FK guard]
  US006 --> RS2{US-REVIEW-S2}
  US007 --> RS2
  RS2 --> US008[US-008 HTMX page]
  RS2 --> US009[US-009 create_tenant script]
  RS2 --> US010[US-010 CI matrix]
  US008 --> US011[US-011 Mutation check]
  US010 --> US011
  US011 --> US012[US-012 README]
  US009 --> US012
  US012 --> RS3{US-REVIEW-S3}
```

---

## Sprint 0: Bootstrap (~10 min)

**Priority:** Critical
**Purpose:** Project skeleton, venv, MariaDB running, one green test.
**Status:** Not started

- [ ] **US-000** Bootstrap project and environment (~10 min, ~60 lines)

### US-000: Bootstrap project and environment (~10 min, ~60 lines)

**Implementation:**
- File: `pyproject.toml` with deps fastapi, sqlalchemy[asyncio]>=2.0, alembic, aiomysql, aiosqlite, jinja2, python-multipart, uvicorn; extra `dev`: pytest, pytest-asyncio, httpx. `[tool.pytest.ini_options] asyncio_mode = "auto"`.
- File: `app/main.py` with `GET /health → {"ok": true}`.
- File: `docker-compose.yml` with a `mariadb:11` service (db `workorders`, user/pass `app/app`) and `scripts/mariadb-init.sql` creating `workorders_test`.
- File: `.gitignore` (venv, caches, `*.db`, `.env`).
- Substitute all `{{VARIABLES}}` in this PRD.

**Approach:**
- Write `tests/test_health.py` first; watch it fail; then add the endpoint.

**Do NOT:**
- Open or copy from `{{REFERENCE_DIR}}` yet.

**Acceptance Criteria:**
- Run: `pytest -q` → Expected: `1 passed`
- Run: `docker compose up -d && docker compose ps` → Expected: mariadb `healthy`
- Verify: `grep '{{' PRD_WORKORDER.md` returns nothing

---

## Sprint 1: Data Model, Migrations, Tenancy (~40 min)

**Priority:** Critical
**Purpose:** Schema, migrations proven equal to models, API-key tenant resolution.
**Status:** Not started

- [ ] **US-001** Models and async DB layer (~10 min, ~110 lines) [depends: US-000]
- [ ] **US-002** Alembic migration + migration test (~15 min, ~120 lines) [depends: US-001]
- [ ] **US-003** Tenant resolution from hashed API key (~10 min, ~80 lines) [depends: US-001]
- [ ] **US-REVIEW-S1** Sprint 1 Review 🚧 GATE (~5 min) [depends: US-002, US-003]

### US-001: Models and async DB layer (~10 min, ~110 lines)

**Implementation:**
- File: `app/db.py`: `Base`, `make_engine(url, **kw)` that turns on `PRAGMA foreign_keys=ON` for SQLite, `SessionLocal`, `get_session()` dependency. URL from `DATABASE_URL` env, default `sqlite+aiosqlite:///./dev.db`.
- File: `app/models.py`:
  - `Tenant(id, name String(120), api_key_hash String(64) unique)`
  - `Site(id, tenant_id FK, name String(120))`, unique `(tenant_id, name)`, unique `(id, tenant_id)`
  - `WorkOrder(id, tenant_id FK, site_id, title String(200), description Text, status, priority, created_at, updated_at)`
  - `Status` enum: open, in_progress, done, cancelled. `Priority`: low, normal, high. Both `Enum(..., native_enum=False)` with explicit length.
  - Composite FK `(site_id, tenant_id) → sites(id, tenant_id)` named `fk_work_orders_site_same_tenant`; index `(tenant_id, status)`.

**Approach:**
- All strings get explicit lengths (MariaDB VARCHAR requires them).
- `server_default=func.now()` for timestamps, `onupdate=func.now()` for `updated_at`.

**Acceptance Criteria:**
- Test: `tests/conftest.py` fixture `engine` creates/drops all tables; uses in-memory SQLite + `StaticPool` by default, `TEST_DATABASE_URL` + `NullPool` when set.
- Run: `pytest -q` → Expected: still green

### US-002: Alembic migration + migration test (~15 min, ~120 lines)

**Implementation:**
- Run: `alembic init -t async alembic`
- File: `alembic/env.py`: `target_metadata = Base.metadata`; URL from `DATABASE_URL` unless `config.attributes["url_set_by_caller"]`; `render_as_batch` only for SQLite; `compare_type=True`; skip `fileConfig` when `config.attributes["configure_logger"] is False`.
- File: `alembic/versions/0001_initial_schema.py`, **hand-written**.
- File: `tests/test_migrations.py`: upgrade head → `command.check` → downgrade base → upgrade head → finally downgrade base. Synchronous test (Alembic's async env calls `asyncio.run`).

**Approach:**
- Autogenerate once to compare, then hand-write. Autogenerate on SQLite emits `sa.text('(CURRENT_TIMESTAMP)')` defaults and batch ops; use `sa.func.now()` and plain `op.create_index` so the file is dialect-neutral.

**Do NOT:**
- Use `Base.metadata.create_all` anywhere outside test fixtures.

**Acceptance Criteria:**
- Run: `alembic upgrade head && alembic check` → Expected: `No new upgrade operations detected.`
- Run: `pytest tests/test_migrations.py -q` → Expected: `1 passed`
- Run: same with `TEST_DATABASE_URL=mysql+aiomysql://app:app@127.0.0.1:3306/workorders_test` → Expected: `1 passed`

### US-003: Tenant resolution from hashed API key (~10 min, ~80 lines)

**Implementation:**
- File: `app/tenancy.py`: `hash_key` (SHA-256 hex), `new_api_key` (`secrets.token_urlsafe(32)`), `get_current_tenant` dependency reading `X-API-Key` header, falling back to `api_key` cookie; 401 if missing or unknown.
- Fixture: `tenants` creates two tenants A and B with known keys; returns objects with `.id`, `.key`, `.headers`.

**Approach:**
- Tests first: missing key → 401, unknown key → 401.

**Do NOT:**
- Store or log raw API keys.

**Acceptance Criteria:**
- Test: `test_missing_api_key_is_rejected`, `test_unknown_api_key_is_rejected` pass
- Verify: `grep -rn "api_key_hash ==" app/` shows the only lookup compares hashes

### US-REVIEW-S1: Sprint 1 Review 🚧 GATE (~5 min)

**Scope:** US-001 to US-003
**Review Steps:**
1. `pytest -q` on SQLite and MariaDB, both green
2. `alembic check` clean
3. Read `models.py` against the US-001 spec line by line

**Linus 5-Layer Analysis:**
1. Data structures: is tenant ownership expressed in the schema, not just code?
2. Special cases: any per-dialect branches beyond the SQLite pragma and batch mode?
3. Complexity: could any file be shorter?
4. Breaking changes: none (greenfield)
5. Practicality: does the test DB setup work on a fresh clone?

**Taste Score:** Good / Acceptable / Needs work, with one line of reasoning
**Test File Checks:** every test asserts something specific; no `assert r.status_code in (...)`
**Gate:** Output `<review-passed/>` or `<review-issues-found/>` with a list. Commit `"docs: US-REVIEW-S1 complete"`.

---

## Sprint 2: API and Tenant Isolation (~50 min)

**Priority:** Critical
**Purpose:** JSON API where tenant isolation and state rules are enforced and tested.
**Status:** Not started

- [ ] **US-004** Sites API (~10 min, ~80 lines) [depends: US-REVIEW-S1]
- [ ] **US-005** Work-order API + isolation tests (~15 min, ~180 lines) [depends: US-004]
- [ ] **US-006** Status transitions with independent oracle (~10 min, ~100 lines) [depends: US-005]
- [ ] **US-007** Database-level cross-tenant guard test (~5 min, ~20 lines) [depends: US-005]
- [ ] **US-REVIEW-S2** Sprint 2 Review 🚧 GATE (~5 min) [depends: US-006, US-007]

### US-004: Sites API (~10 min, ~80 lines)

**Implementation:**
- File: `app/services.py`: `create_site`, `list_sites`, `get_site`; exceptions `NotFound`, `Conflict`.
- File: `app/routers/api.py`: `POST /api/sites` (201, 409 on duplicate name within tenant), `GET /api/sites`.
- File: `app/schemas.py`: `SiteIn` (name 1–120), `SiteOut`.

**Acceptance Criteria:**
- Test: duplicate name in same tenant → 409; same name in another tenant → 201
- Test: B's site list never includes A's sites

### US-005: Work-order API + isolation tests (~15 min, ~180 lines)

**Implementation:**
- Services: `create_work_order` (calls `get_site(tenant_id, site_id)` first), `list_work_orders(status=None)`, `get_work_order`.
- Routes: `POST /api/work-orders`, `GET /api/work-orders?status_filter=`, `GET /api/work-orders/{id}`.
- File: `tests/test_tenant_isolation.py`.

**Approach:**
- Write all isolation tests before the services:
  - list returns only own orders (both directions)
  - GET another tenant's order → **404** (not 403)
  - create on another tenant's site → 404
- **Functional:** every service function's first parameter after `session` is `tenant_id`.

**Do NOT:**
- Add any query on `WorkOrder` or `Site` without a `tenant_id` predicate.

**Acceptance Criteria:**
- Run: `pytest tests/test_tenant_isolation.py -q` → Expected: all pass
- Verify: `grep -n "select(WorkOrder)\|select(Site)" app/services.py`; every hit is followed by a `tenant_id` filter

### US-006: Status transitions with independent oracle (~10 min, ~100 lines)

**Implementation:**
- `ALLOWED_TRANSITIONS`: open→{in_progress, cancelled}; in_progress→{done, open, cancelled}; done→{}; cancelled→{}.
- `change_status` raises `InvalidTransition` → route returns 409. Route `PATCH /api/work-orders/{id}/status`.
- Tests: `EXPECTED_ALLOWED` written out **by hand** in the test file; one test asserts the table equals it; a parametrized test covers every disallowed pair (11 cases) and asserts status is unchanged after the 409.

**Do NOT:**
- Generate test cases from `ALLOWED_TRANSITIONS`. That is a tautology: a wrong table produces matching wrong tests. (The reference build hit exactly this; see its README.)

**Acceptance Criteria:**
- Test: `test_transition_table_matches_spec`, 11× `test_disallowed_transitions_are_refused`, `test_happy_path_open_to_done` pass
- Test: cross-tenant PATCH → 404 and the order is still `open`

### US-007: Database-level cross-tenant guard test (~5 min, ~20 lines)

**Implementation:**
- Test: bypass the service layer, insert `WorkOrder(tenant_id=B, site_id=<A's site>)` directly via a session → `IntegrityError` on commit.

**Acceptance Criteria:**
- Run on SQLite and MariaDB → Expected: passes on both (proves the composite FK exists in both)

### US-REVIEW-S2: Sprint 2 Review 🚧 GATE (~5 min)

**Scope:** US-004 to US-007
**Review Steps:** full suite on both DBs; read every query in `services.py`; compare endpoint behavior with `{{REFERENCE_DIR}}` (run both, hit the same requests, diff the JSON)
**Linus 5-Layer Analysis:** as in S1, plus: is 404-vs-403 consistent across every endpoint?
**Cross-Task Checks:** no route touches the DB except through `services.py`
**Gate:** `<review-passed/>` or `<review-issues-found/>`; commit `"docs: US-REVIEW-S2 complete"`

---

## Sprint 3: UI, CI, Proof of Tests, Docs (~50 min)

**Priority:** High
**Purpose:** HTMX page, CI on both DBs, evidence that tests catch real bugs.
**Status:** Not started

- [ ] **US-008** HTMX page and row partial (~15 min, ~120 lines) [depends: US-REVIEW-S2]
- [ ] **US-009** create_tenant script (~5 min, ~40 lines) [depends: US-REVIEW-S2]
- [ ] **US-010** GitHub Actions matrix: SQLite + MariaDB (~10 min, ~45 lines) [depends: US-REVIEW-S2]
- [ ] **US-011** Mutation check (~10 min, 0 lines kept) [depends: US-008, US-010]
- [ ] **US-012** README (~10 min, ~100 lines) [depends: US-009, US-011]
- [ ] **US-REVIEW-S3** Final Review 🚧 GATE (~5 min) [depends: US-012]

### US-008: HTMX page and row partial (~15 min, ~120 lines)

**Implementation:**
- `app/templates/index.html` (Tailwind CDN + htmx 2), `_row.html` with one button per allowed next status: `hx-post="/ui/work-orders/{id}/status" hx-target="#wo-{id}" hx-swap="outerHTML"`.
- `app/routers/ui.py`: `GET /` (cookie auth), `POST /ui/work-orders/{id}/status` (form field `new_status`) returning **only** the `<tr>` partial.

**Acceptance Criteria:**
- Test: page via cookie shows own orders, not the other tenant's
- Test: partial starts with `<tr id="wo-{id}"`, contains `data-status="in_progress"`, has no `<html`
- Test: cross-tenant UI post → 404

### US-009: create_tenant script (~5 min, ~40 lines)

**Implementation:**
- `scripts/create_tenant.py "Name" [--demo]`: creates a tenant, prints the raw key **once**, optional demo site + 2 orders.

**Acceptance Criteria:**
- Run: `alembic upgrade head && python -m scripts.create_tenant "Acme" --demo` then `curl -H "X-API-Key: <key>" localhost:8000/api/work-orders` → Expected: 2 orders

### US-010: GitHub Actions matrix (~10 min, ~45 lines)

**Implementation:**
- `.github/workflows/ci.yml`: on push to main and PRs; matrix `db: [sqlite, mariadb]`; `mariadb:11` service with healthcheck `healthcheck.sh --connect --innodb_initialized`; MariaDB leg sets `TEST_DATABASE_URL`.

**Acceptance Criteria:**
- Verify: after push, `gh run watch` → both legs green

### US-011: Mutation check (~10 min, 0 lines kept)

**Approach:** For each injected bug: apply it, run `pytest -q`, record the failure count, then `git checkout app/services.py`.
1. Drop `tenant_id` from `get_work_order`
2. Drop `tenant_id` from `list_work_orders`
3. Drop `tenant_id` from `get_site`
4. Add `done → open` to `ALLOWED_TRANSITIONS`

**Do NOT:**
- Commit any mutated code. `git diff` must be empty at the end.

**Acceptance Criteria:**
- Expected: every mutation fails ≥1 test. Any mutation that survives is a test gap: add a test, re-run, and log it in the defect ledger.

### US-012: README (~10 min, ~100 lines)

**Implementation:** What it is; a table of tenant-safety measures; run with SQLite or MariaDB; test commands; mutation-check results table from US-011; layout; API table.
**Do NOT:** claim anything not demonstrated by a test or command in this PRD.

### US-REVIEW-S3: Final Review 🚧 GATE (~5 min)

**Review Steps:** fresh clone → venv → `pytest` green; CI green; README commands run as written; diff test names vs `{{REFERENCE_DIR}}/tests`
**Gate:** `<review-passed/>` or `<review-issues-found/>`; commit `"docs: US-REVIEW-S3 complete"`

---

## Non-Goals

- User accounts, passwords, OAuth (API keys only)
- Pagination, search, file attachments
- Production deployment, Dockerfile for the app
- React or any SPA

## Technical Considerations

**Existing Files:** none in `{{PROJECT_DIR}}`; reference in `{{REFERENCE_DIR}}` is read-only.
**Dependencies:** SQLAlchemy 2.x async API (`AsyncSession`, `async_sessionmaker`, `scalars`, `scalar`).
**Platform Notes:** SQLite needs the FK pragma or the composite-FK test silently passes for the wrong reason. In-memory SQLite needs `StaticPool` so all sessions share one DB.
**Safety Constraints:** never print or log raw API keys except the one-time output of `create_tenant`.
**Known Limitations:** `updated_at` uses `onupdate=func.now()` (set by ORM updates, not raw SQL).

## Post-Build Verification

**Tests**
- [ ] `pytest` green on SQLite
- [ ] `pytest` green on MariaDB
- [ ] All 4 mutations caught

**Schema**
- [ ] `alembic check` clean
- [ ] Downgrade/upgrade round-trip clean

**Repo**
- [ ] CI green on both legs
- [ ] README commands work from a fresh clone
- [ ] No raw keys, `.env`, or `*.db` committed

## Maintenance

- **New column:** change model → write migration by hand → `pytest tests/test_migrations.py` (fails until they agree)
- **Troubleshooting:** MariaDB `Access denied` → `docker compose down -v` to re-run the init script; `IntegrityError` in the FK test on SQLite missing → the pragma listener isn't attached

## Changelog

- 1.0.0 (2026-10-09): initial PRD, written alongside the reference implementation
