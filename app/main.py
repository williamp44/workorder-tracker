from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app import services
from app.routers import api, ui

app = FastAPI(title="Work-Order Tracker")

# One place maps service errors to HTTP. Another tenant's row raises NotFound,
# the same as a missing row, so it is a 404 and never a 403.
STATUS_FOR: dict[type[Exception], int] = {
    services.NotFound: status.HTTP_404_NOT_FOUND,
    services.InvalidTransition: status.HTTP_409_CONFLICT,
    services.Conflict: status.HTTP_409_CONFLICT,
}


async def service_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=STATUS_FOR[type(exc)])


for _error in STATUS_FOR:
    app.add_exception_handler(_error, service_error)
app.include_router(api.router)
app.include_router(ui.router)


@app.get("/health")
async def health():
    return {"ok": True}
