"""Create a tenant (and optionally a demo site and work orders); prints its API key once.

    python -m scripts.create_tenant "Acme Vending" --demo
"""

import argparse
import asyncio

from app import services
from app.db import SessionLocal, engine
from app.models import Priority, Tenant
from app.tenancy import hash_key, new_api_key


async def main(name: str, demo: bool) -> None:
    key = new_api_key()
    async with SessionLocal() as s:
        tenant = Tenant(name=name, api_key_hash=hash_key(key))
        s.add(tenant)
        await s.commit()
        if demo:
            site = await services.create_site(s, tenant.id, "Lobby micro market")
            await services.create_work_order(s, tenant.id, site.id, "Restock cold case", priority=Priority.high)
            await services.create_work_order(s, tenant.id, site.id, "Card reader offline")
    await engine.dispose()
    print(f"Tenant {name!r} created (id={tenant.id}).")
    print(f"API key (shown once, only its hash is stored): {key}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("--demo", action="store_true", help="add a sample site and work orders")
    args = p.parse_args()
    asyncio.run(main(args.name, args.demo))
