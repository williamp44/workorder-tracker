"""Test fixtures.

Default: in-memory SQLite (fast, no setup).
CI sets TEST_DATABASE_URL to a real MariaDB so the same suite runs against
the production database engine.
"""

import os
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.db import Base, get_session, make_engine
from app.main import app
from app.models import Tenant
from app.tenancy import hash_key

def pytest_collection_modifyitems(items):
    """Record controls in the JUnit report for tools/check_red.py.

    A control is a test that is green before the change by design: it pins
    behaviour that must keep working. It must say why.
    """
    for item in items:
        marker = item.get_closest_marker("control")
        if marker is None:
            continue
        reason = marker.args[0] if marker.args else ""
        if not str(reason).strip():
            raise pytest.UsageError(f"{item.nodeid}: @pytest.mark.control needs a reason")
        item.user_properties.append(("control", reason))


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite://")


@pytest.fixture
async def engine():
    if TEST_DATABASE_URL == "sqlite+aiosqlite://":
        eng = make_engine(TEST_DATABASE_URL, poolclass=StaticPool)
    else:
        eng = make_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def client(session_factory):
    async def _session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@dataclass(frozen=True)
class TenantCtx:
    id: int
    key: str

    @property
    def headers(self) -> dict[str, str]:
        return {"X-API-Key": self.key}


@pytest.fixture
async def tenants(session_factory) -> tuple[TenantCtx, TenantCtx]:
    """Two tenants, A and B, each with its own API key."""
    out = []
    async with session_factory() as s:
        for name, key in (("Acme Vending", "key-acme"), ("Bolt Markets", "key-bolt")):
            t = Tenant(name=name, api_key_hash=hash_key(key))
            s.add(t)
            await s.flush()
            out.append(TenantCtx(t.id, key))
        await s.commit()
    return out[0], out[1]


async def make_site(client, tenant: TenantCtx, name: str = "Main St") -> int:
    r = await client.post("/api/sites", json={"name": name}, headers=tenant.headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def make_order(client, tenant: TenantCtx, site_id: int, title: str = "Fix coil 4") -> dict:
    r = await client.post(
        "/api/work-orders", json={"site_id": site_id, "title": title}, headers=tenant.headers
    )
    assert r.status_code == 201, r.text
    return r.json()
