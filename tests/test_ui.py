from tests.conftest import make_order, make_site


async def test_index_lists_own_orders_via_cookie(client, tenants):
    a, b = tenants
    await make_order(client, a, await make_site(client, a), "Acme job")
    await make_order(client, b, await make_site(client, b), "Bolt job")

    client.cookies.set("api_key", a.key)
    r = await client.get("/")
    client.cookies.clear()
    assert r.status_code == 200
    assert "Acme job" in r.text
    assert "Bolt job" not in r.text


async def test_htmx_status_change_returns_updated_row(client, tenants):
    a, _ = tenants
    order = await make_order(client, a, await make_site(client, a))
    r = await client.post(
        f"/ui/work-orders/{order['id']}/status",
        data={"new_status": "in_progress"},
        headers={**a.headers, "HX-Request": "true"},
    )
    assert r.status_code == 200
    # A single <tr> partial, not a full page, with the new status and next actions.
    assert r.text.lstrip().startswith(f'<tr id="wo-{order["id"]}"')
    assert 'data-status="in_progress"' in r.text
    assert "<html" not in r.text
