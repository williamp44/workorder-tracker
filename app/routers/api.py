from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import services
from app.db import get_session
from app.models import Status, Tenant
from app.schemas import SiteIn, SiteOut, StatusChange, WorkOrderIn, WorkOrderOut
from app.tenancy import get_current_tenant

router = APIRouter(prefix="/api")


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
async def create_site(
    body: SiteIn,
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await services.create_site(session, tenant.id, body.name)
    except services.Conflict as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    return await services.list_sites(session, tenant.id)


@router.post("/work-orders", response_model=WorkOrderOut, status_code=status.HTTP_201_CREATED)
async def create_work_order(
    body: WorkOrderIn,
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await services.create_work_order(
            session, tenant.id, body.site_id, body.title, body.description, body.priority
        )
    except services.NotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.get("/work-orders", response_model=list[WorkOrderOut])
async def list_work_orders(
    status_filter: Status | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    return await services.list_work_orders(session, tenant.id, status_filter)


@router.get("/work-orders/{wo_id}", response_model=WorkOrderOut)
async def get_work_order(
    wo_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await services.get_work_order(session, tenant.id, wo_id)
    except services.NotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.patch("/work-orders/{wo_id}/status", response_model=WorkOrderOut)
async def change_status(
    wo_id: int,
    body: StatusChange,
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await services.change_status(session, tenant.id, wo_id, body.status)
    except services.NotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except services.InvalidTransition as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
