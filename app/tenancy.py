"""Resolve the calling tenant from an API key.

Every data-access path takes the Tenant this returns; nothing in the app
queries tenant-owned rows without it.
"""

import hashlib
import secrets

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Tenant


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def new_api_key() -> str:
    return secrets.token_urlsafe(32)


async def get_current_tenant(
    x_api_key: str | None = Header(default=None),
    api_key: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> Tenant:
    raw = x_api_key or api_key
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
    tenant = await session.scalar(select(Tenant).where(Tenant.api_key_hash == hash_key(raw)))
    if tenant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return tenant
