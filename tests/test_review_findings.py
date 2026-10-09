"""Defects found by review and tooling on 2026-10-09, one test each.

Every test here was written before its fix and seen failing. docs/CHECKS.md
records which check found each one.
"""

import pytest
from sqlalchemy import update

from app import services
from app.models import Status, WorkOrder
from tests.conftest import make_order, make_site

MAX_ID = 2**31 - 1  # signed 32-bit INTEGER: the id column on MariaDB


async def _order_in_progress(session_factory, tenant_id: int) -> int:
    async with session_factory() as s:
        site = await services.create_site(s, tenant_id, "Depot")
        wo = await services.create_work_order(s, tenant_id, site.id, "Fix coil 4")
        await services.change_status(s, tenant_id, wo.id, Status.in_progress)
        return wo.id


# Found by: adversarial review (two concurrent PATCHes ended done -> cancelled).
async def test_status_change_refuses_when_another_request_moved_it_first(
    tenants, session_factory, monkeypatch
):
    a, _ = tenants
    wo_id = await _order_in_progress(session_factory, a.id)

    real_get = services.get_work_order

    async def read_then_lose_the_race(session, tenant_id, wo_id_):
        found = await real_get(session, tenant_id, wo_id_)
        # Another request finishes the order after this one has read it.
        async with session_factory() as other:
            await other.execute(
                update(WorkOrder).where(WorkOrder.id == wo_id_).values(status=Status.done)
            )
            await other.commit()
        return found

    monkeypatch.setattr(services, "get_work_order", read_then_lose_the_race)
    async with session_factory() as s:
        with pytest.raises(services.InvalidTransition):
            await services.change_status(s, a.id, wo_id, Status.cancelled)

    monkeypatch.undo()
    async with session_factory() as s:
        assert (await services.get_work_order(s, a.id, wo_id)).status == Status.done


# Found by: adversarial review (a cross-site <form> POST with only the cookie got 200).
async def test_ui_status_post_with_only_a_cookie_is_refused(client, tenants):
    a, _ = tenants
    order = await make_order(client, a, await make_site(client, a))
    client.cookies.set("api_key", a.key)
    r = await client.post(
        f"/ui/work-orders/{order['id']}/status", data={"new_status": "cancelled"}
    )
    client.cookies.clear()
    assert r.status_code == 403
    r = await client.get(f"/api/work-orders/{order['id']}", headers=a.headers)
    assert r.json()["status"] == "open"


async def test_ui_status_post_from_htmx_with_cookie_still_works(client, tenants):
    a, _ = tenants
    order = await make_order(client, a, await make_site(client, a))
    client.cookies.set("api_key", a.key)
    r = await client.post(
        f"/ui/work-orders/{order['id']}/status",
        data={"new_status": "in_progress"},
        headers={"HX-Request": "true"},
    )
    client.cookies.clear()
    assert r.status_code == 200


# Found by: Linus review and adversarial review (check-then-insert race gave a 500).
async def test_duplicate_site_that_races_past_the_check_is_still_a_conflict(
    tenants, session_factory
):
    a, _ = tenants
    async with session_factory() as s:
        await services.create_site(s, a.id, "Lobby")
    async with session_factory() as s:

        async def nothing_found(*_args, **_kwargs):
            return None  # the other request inserted after this one looked

        s.scalar = nothing_found  # type: ignore[method-assign]
        with pytest.raises(services.Conflict):
            await services.create_site(s, a.id, "Lobby")


# Found by: adversarial review (OverflowError -> unhandled 500).
@pytest.mark.parametrize("method,path", [
    ("GET", f"/api/work-orders/{MAX_ID + 1}"),
    ("PATCH", f"/api/work-orders/{MAX_ID + 1}/status"),
    ("GET", "/api/work-orders/99999999999999999999"),
    ("GET", "/api/work-orders/0"),
])
async def test_out_of_range_ids_are_rejected_not_crashed(client, tenants, method, path):
    a, _ = tenants
    r = await client.request(method, path, json={"status": "done"}, headers=a.headers)
    assert r.status_code == 422


async def test_out_of_range_site_id_in_body_is_rejected(client, tenants):
    a, _ = tenants
    r = await client.post(
        "/api/work-orders", json={"site_id": 99999999999999999999, "title": "x"},
        headers=a.headers,
    )
    assert r.status_code == 422


# Found by: adversarial review ("   " accepted as a site name).
@pytest.mark.parametrize("path,body", [
    ("/api/sites", {"name": "   "}),
    ("/api/work-orders", {"site_id": 1, "title": "   "}),
])
async def test_blank_names_are_rejected(client, tenants, path, body):
    a, _ = tenants
    r = await client.post(path, json=body, headers=a.headers)
    assert r.status_code == 422


async def test_names_are_stored_trimmed(client, tenants):
    a, _ = tenants
    r = await client.post("/api/sites", json={"name": "  Lobby  "}, headers=a.headers)
    assert r.json()["name"] == "Lobby"


# Found by: CI on MariaDB 11 (snapshot isolation raised 1020 -> a 500).
async def test_a_snapshot_conflict_from_the_database_is_a_409_not_a_500(
    tenants, session_factory, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    a, _ = tenants
    wo_id = await _order_in_progress(session_factory, a.id)
    async with session_factory() as s:
        real_execute = s.execute

        async def conflict_on_update(statement, *args, **kwargs):
            if getattr(statement, "is_update", False):
                orig = Exception(1020, "Record has changed since last read in table 'work_orders'")
                raise OperationalError(str(statement), {}, orig)
            return await real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(s, "execute", conflict_on_update)
        with pytest.raises(services.InvalidTransition):
            await services.change_status(s, a.id, wo_id, Status.done)


async def test_other_database_errors_are_not_disguised_as_conflicts(
    tenants, session_factory, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    a, _ = tenants
    wo_id = await _order_in_progress(session_factory, a.id)
    async with session_factory() as s:
        real_execute = s.execute

        async def lost_connection(statement, *args, **kwargs):
            if getattr(statement, "is_update", False):
                raise OperationalError(str(statement), {}, Exception(2013, "Lost connection"))
            return await real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(s, "execute", lost_connection)
        with pytest.raises(OperationalError):
            await services.change_status(s, a.id, wo_id, Status.done)
