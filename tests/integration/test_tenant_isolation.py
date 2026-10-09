"""The most important tests in the repo: one tenant can never see or touch
another tenant's data, through any endpoint."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import WorkOrder
from tests.conftest import make_order, make_site


async def test_missing_api_key_is_rejected(client):
    r = await client.get("/api/work-orders")
    assert r.status_code == 401


@pytest.mark.usefixtures("tenants")  # real keys exist, so 401 is not just an empty table
async def test_unknown_api_key_is_rejected(client):
    r = await client.get("/api/work-orders", headers={"X-API-Key": "not-a-real-key"})
    assert r.status_code == 401


async def test_list_shows_only_own_work_orders(client, tenants):
    a, b = tenants
    order_a = await make_order(client, a, await make_site(client, a))
    order_b = await make_order(client, b, await make_site(client, b))

    ids_a = [o["id"] for o in (await client.get("/api/work-orders", headers=a.headers)).json()]
    ids_b = [o["id"] for o in (await client.get("/api/work-orders", headers=b.headers)).json()]
    assert ids_a == [order_a["id"]]
    assert ids_b == [order_b["id"]]


async def test_list_sites_shows_only_own_sites(client, tenants):
    a, b = tenants
    await make_site(client, a, "A site")
    await make_site(client, b, "B site")
    names = [s["name"] for s in (await client.get("/api/sites", headers=b.headers)).json()]
    assert names == ["B site"]


async def test_other_tenants_work_order_reads_as_not_found(client, tenants):
    a, b = tenants
    order = await make_order(client, a, await make_site(client, a))

    r = await client.get(f"/api/work-orders/{order['id']}", headers=b.headers)
    # 404, not 403: B must not learn that the ID exists.
    assert r.status_code == 404


async def test_cannot_change_status_of_other_tenants_work_order(client, tenants):
    a, b = tenants
    order = await make_order(client, a, await make_site(client, a))

    r = await client.patch(
        f"/api/work-orders/{order['id']}/status", json={"status": "cancelled"}, headers=b.headers
    )
    assert r.status_code == 404
    r = await client.get(f"/api/work-orders/{order['id']}", headers=a.headers)
    assert r.json()["status"] == "open"


async def test_cannot_create_work_order_on_other_tenants_site(client, tenants):
    a, b = tenants
    site_a = await make_site(client, a)
    r = await client.post(
        "/api/work-orders", json={"site_id": site_a, "title": "sneaky"}, headers=b.headers
    )
    assert r.status_code == 404


async def test_ui_status_change_is_tenant_scoped(client, tenants):
    a, b = tenants
    order = await make_order(client, a, await make_site(client, a))
    r = await client.post(
        f"/ui/work-orders/{order['id']}/status",
        data={"new_status": "in_progress"},
        headers={**b.headers, "HX-Request": "true"},  # past the CSRF guard, to the tenant check
    )
    assert r.status_code == 404


async def test_database_rejects_cross_tenant_site_even_if_app_code_is_bypassed(
    client, tenants, session_factory
):
    """Defense in depth: the composite foreign key stops a bug in the service
    layer from writing a work order that points at another tenant's site."""
    a, b = tenants
    site_a = await make_site(client, a)
    async with session_factory() as s:
        s.add(WorkOrder(tenant_id=b.id, site_id=site_a, title="bypass", description=""))
        with pytest.raises(IntegrityError):
            await s.commit()
