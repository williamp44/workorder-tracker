"""Tenant-scoped data access.

Rule: every function takes tenant_id and filters on it. A row belonging to
another tenant is indistinguishable from a row that doesn't exist (NotFound),
so callers can't probe for other tenants' IDs.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Priority, Site, Status, WorkOrder


class NotFound(Exception):
    pass


class InvalidTransition(Exception):
    pass


class Conflict(Exception):
    pass


ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    Status.open: {Status.in_progress, Status.cancelled},
    Status.in_progress: {Status.done, Status.open, Status.cancelled},
    Status.done: set(),
    Status.cancelled: set(),
}


async def create_site(session: AsyncSession, tenant_id: int, name: str) -> Site:
    exists = await session.scalar(
        select(Site.id).where(Site.tenant_id == tenant_id, Site.name == name)
    )
    if exists:
        raise Conflict(f"Site {name!r} already exists")
    site = Site(tenant_id=tenant_id, name=name)
    session.add(site)
    await session.commit()
    return site


async def list_sites(session: AsyncSession, tenant_id: int) -> list[Site]:
    rows = await session.scalars(select(Site).where(Site.tenant_id == tenant_id).order_by(Site.name))
    return list(rows)


async def get_site(session: AsyncSession, tenant_id: int, site_id: int) -> Site:
    site = await session.scalar(select(Site).where(Site.id == site_id, Site.tenant_id == tenant_id))
    if site is None:
        raise NotFound("Site not found")
    return site


async def create_work_order(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
    title: str,
    description: str = "",
    priority: Priority = Priority.normal,
) -> WorkOrder:
    # The site must belong to the same tenant; otherwise a tenant could attach
    # work orders to another tenant's site by guessing its ID.
    await get_site(session, tenant_id, site_id)
    wo = WorkOrder(
        tenant_id=tenant_id,
        site_id=site_id,
        title=title,
        description=description,
        priority=priority,
        status=Status.open,
    )
    session.add(wo)
    await session.commit()
    await session.refresh(wo)
    return wo


async def list_work_orders(
    session: AsyncSession, tenant_id: int, status: Status | None = None
) -> list[WorkOrder]:
    q = select(WorkOrder).where(WorkOrder.tenant_id == tenant_id)
    if status is not None:
        q = q.where(WorkOrder.status == status)
    rows = await session.scalars(q.order_by(WorkOrder.id))
    return list(rows)


async def get_work_order(session: AsyncSession, tenant_id: int, wo_id: int) -> WorkOrder:
    wo = await session.scalar(
        select(WorkOrder).where(WorkOrder.id == wo_id, WorkOrder.tenant_id == tenant_id)
    )
    if wo is None:
        raise NotFound("Work order not found")
    return wo


async def change_status(
    session: AsyncSession, tenant_id: int, wo_id: int, new_status: Status
) -> WorkOrder:
    wo = await get_work_order(session, tenant_id, wo_id)
    if new_status not in ALLOWED_TRANSITIONS[wo.status]:
        raise InvalidTransition(f"Cannot move from {wo.status.value} to {new_status.value}")
    wo.status = new_status
    await session.commit()
    await session.refresh(wo)
    return wo
