from fastapi import FastAPI

from app.routers import api, ui

app = FastAPI(title="Work-Order Tracker")
app.include_router(api.router)
app.include_router(ui.router)


@app.get("/health")
async def health():
    return {"ok": True}
