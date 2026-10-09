"""Tenant-scoped data access.

Rule: every function takes tenant_id and filters on it. A row belonging to
another tenant is indistinguishable from a row that doesn't exist (NotFound),
so callers can't probe for other tenants' IDs.
"""

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Priority, Site, Status, WorkOrder
from app.rules import can_transition


class NotFound(Exception):
    pass


class InvalidTransition(Exception):
    pass


class Conflict(Exception):
    pass


RECORD_CHANGED = 1020  # MariaDB: "Record has changed since last read"



async def create_site(session: AsyncSession, tenant_id: int, name: str) -> Site:
    # The unique constraint (tenant_id, name) is the check. A SELECT first
    # would race: two requests can both see "no such site" and both insert.
    site = Site(tenant_id=tenant_id, name=name)
    session.add(site)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise Conflict(f"Site {name!r} already exists") from None
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
    current = wo.status
    if not can_transition(current, new_status):
        raise InvalidTransition(f"Cannot move from {current.value} to {new_status.value}")
    # Write only if the status is still the one the check above approved.
    # Another request may have moved it since we read it; a plain write would
    # let done -> cancelled through without ever consulting the table.
    try:
        result = await session.execute(
            update(WorkOrder)
            .where(WorkOrder.id == wo_id, WorkOrder.tenant_id == tenant_id, WorkOrder.status == current)
            .values(status=new_status)
        )
    except OperationalError as e:
        # MariaDB 11 detects the same race itself, under snapshot isolation,
        # and raises 1020 instead of updating zero rows. Same conflict.
        if e.orig is None or e.orig.args[:1] != (RECORD_CHANGED,):
            raise
        await session.rollback()
        raise InvalidTransition(f"Work order is no longer {current.value}; reload and retry") from None
    assert isinstance(result, CursorResult)  # an UPDATE always returns one
    if result.rowcount != 1:
        await session.rollback()
        raise InvalidTransition(f"Work order is no longer {current.value}; reload and retry")
    await session.commit()
    await session.refresh(wo)
    return wo
