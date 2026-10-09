from datetime import datetime
from typing import Annotated

from fastapi import Path
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import Priority, Status


# Ids are signed 32-bit INTEGER columns on MariaDB. Anything outside that
# range cannot exist, and passing it to the driver overflows into a 500.
MAX_ID = 2**31 - 1
RowId = Annotated[int, Field(ge=1, le=MAX_ID)]
PathId = Annotated[int, Path(ge=1, le=MAX_ID)]


# Names are trimmed, and must not be blank once trimmed.
SiteName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class SiteIn(BaseModel):
    name: SiteName


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class WorkOrderIn(BaseModel):
    site_id: RowId
    title: Title
    description: str = ""
    priority: Priority = Priority.normal


class StatusChange(BaseModel):
    status: Status


class WorkOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    site_id: int
    title: str
    description: str
    status: Status
    priority: Priority
    created_at: datetime
    updated_at: datetime
