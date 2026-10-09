from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import services
from app.db import get_session
from app.models import Status, Tenant
from app.services import ALLOWED_TRANSITIONS
from app.tenancy import get_current_tenant

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
templates.env.globals["ALLOWED"] = ALLOWED_TRANSITIONS

router = APIRouter()


@router.get("/")
async def index(
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    orders = await services.list_work_orders(session, tenant.id)
    sites = {s.id: s.name for s in await services.list_sites(session, tenant.id)}
    return templates.TemplateResponse(
        request, "index.html", {"tenant": tenant, "orders": orders, "sites": sites}
    )


@router.post("/ui/work-orders/{wo_id}/status")
async def change_status_partial(
    request: Request,
    wo_id: int,
    new_status: Status = Form(...),
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    """HTMX target: returns just the updated <tr> to swap in place."""
    try:
        wo = await services.change_status(session, tenant.id, wo_id, new_status)
    except services.NotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except services.InvalidTransition as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    site = await services.get_site(session, tenant.id, wo.site_id)
    return templates.TemplateResponse(
        request, "_row.html", {"wo": wo, "sites": {site.id: site.name}}
    )
