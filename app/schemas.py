from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import Priority, Status


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class WorkOrderIn(BaseModel):
    site_id: int
    title: str = Field(min_length=1, max_length=200)
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
