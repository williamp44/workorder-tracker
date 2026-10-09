from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Header, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import services
from app.db import get_session
from app.models import Status, Tenant
from app.schemas import PathId
from app.services import ALLOWED_TRANSITIONS
from app.tenancy import get_current_tenant

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
# Jinja's stubs type `globals` as its built-ins only; any added value is
# flagged. The value is read by _row.html, which both views render.
templates.env.globals["ALLOWED"] = ALLOWED_TRANSITIONS  # pyrefly: ignore[unsupported-operation]

router = APIRouter()


def require_htmx(hx_request: str | None = Header(default=None)) -> None:
    """CSRF guard for cookie-authenticated POSTs.

    A cross-site <form> can POST with the user's cookie, but it cannot set a
    custom header without a CORS preflight, which this app never grants.
    HTMX sends HX-Request on every request it makes.
    """
    if hx_request != "true":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "HX-Request header required")


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


@router.post("/ui/work-orders/{wo_id}/status", dependencies=[Depends(require_htmx)])
async def change_status_partial(
    request: Request,
    wo_id: PathId,
    new_status: Status = Form(...),
    tenant: Tenant = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    """HTMX target: returns just the updated <tr> to swap in place."""
    wo = await services.change_status(session, tenant.id, wo_id, new_status)
    site = await services.get_site(session, tenant.id, wo.site_id)
    return templates.TemplateResponse(
        request, "_row.html", {"wo": wo, "sites": {site.id: site.name}}
    )
