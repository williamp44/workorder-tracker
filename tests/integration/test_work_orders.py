import pytest

from app.models import Status
from app.rules import ALLOWED_TRANSITIONS
from tests.conftest import make_order, make_site
from tests.spec import EXPECTED_ALLOWED


async def test_create_work_order_defaults(client, tenants):
    a, _ = tenants
    site = await make_site(client, a)
    order = await make_order(client, a, site, "Restock micro market")
    assert order["status"] == "open"
    assert order["priority"] == "normal"
    assert order["site_id"] == site


async def test_title_is_required(client, tenants):
    a, _ = tenants
    site = await make_site(client, a)
    r = await client.post(
        "/api/work-orders", json={"site_id": site, "title": ""}, headers=a.headers
    )
    assert r.status_code == 422


async def test_duplicate_site_name_within_tenant_conflicts(client, tenants):
    a, b = tenants
    await make_site(client, a, "Lobby")
    r = await client.post("/api/sites", json={"name": "Lobby"}, headers=a.headers)
    assert r.status_code == 409
    # Same name under a different tenant is fine.
    await make_site(client, b, "Lobby")


async def test_filter_by_status(client, tenants):
    a, _ = tenants
    site = await make_site(client, a)
    first = await make_order(client, a, site, "one")
    await make_order(client, a, site, "two")
    await client.patch(
        f"/api/work-orders/{first['id']}/status", json={"status": "in_progress"}, headers=a.headers
    )
    r = await client.get("/api/work-orders?status_filter=in_progress", headers=a.headers)
    assert [o["title"] for o in r.json()] == ["one"]


async def test_happy_path_open_to_done(client, tenants):
    a, _ = tenants
    order = await make_order(client, a, await make_site(client, a))
    for status in ("in_progress", "done"):
        r = await client.patch(
            f"/api/work-orders/{order['id']}/status", json={"status": status}, headers=a.headers
        )
        assert r.status_code == 200
        assert r.json()["status"] == status


# EXPECTED_ALLOWED is the hand-written spec (tests/spec.py), independent of
# the table under test.
DISALLOWED = tuple(
    (src, dst)
    for src in Status
    for dst in Status
    if (src.value, dst.value) not in EXPECTED_ALLOWED
)


def test_transition_table_matches_spec():
    actual = {(s.value, d.value) for s, dsts in ALLOWED_TRANSITIONS.items() for d in dsts}
    assert actual == EXPECTED_ALLOWED


async def _drive_to(client, tenant, wo_id, target: Status):
    path = {
        Status.open: [],
        Status.in_progress: ["in_progress"],
        Status.done: ["in_progress", "done"],
        Status.cancelled: ["cancelled"],
    }[target]
    for step in path:
        r = await client.patch(
            f"/api/work-orders/{wo_id}/status", json={"status": step}, headers=tenant.headers
        )
        assert r.status_code == 200, r.text


@pytest.mark.parametrize("src,dst", DISALLOWED, ids=[f"{s.value}->{d.value}" for s, d in DISALLOWED])
async def test_disallowed_transitions_are_refused(client, tenants, src, dst):
    a, _ = tenants
    order = await make_order(client, a, await make_site(client, a))
    await _drive_to(client, a, order["id"], src)

    r = await client.patch(
        f"/api/work-orders/{order['id']}/status", json={"status": dst.value}, headers=a.headers
    )
    assert r.status_code == 409
    r = await client.get(f"/api/work-orders/{order['id']}", headers=a.headers)
    assert r.json()["status"] == src.value
