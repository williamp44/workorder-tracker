import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Status(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


class Priority(str, enum.Enum):
    low = "low"
    normal = "normal"
    high = "high"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    # Only a SHA-256 hash of the API key is stored; the raw key is shown once at creation.
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_sites_tenant_name"),
        # Target for the composite FK from work_orders (see below).
        UniqueConstraint("id", "tenant_id", name="uq_sites_id_tenant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        # Defense in depth: the database itself refuses a work order whose site
        # belongs to a different tenant, even if application code has a bug.
        ForeignKeyConstraint(
            ["site_id", "tenant_id"],
            ["sites.id", "sites.tenant_id"],
            name="fk_work_orders_site_same_tenant",
        ),
        Index("ix_work_orders_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    site_id: Mapped[int] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[Status] = mapped_column(
        Enum(Status, native_enum=False, length=20, name="status"), default=Status.open
    )
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, native_enum=False, length=10, name="priority"), default=Priority.normal
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
