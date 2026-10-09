"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("api_key_hash"),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_sites_tenant_name"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_sites_id_tenant"),
    )
    op.create_index("ix_sites_tenant_id", "sites", ["tenant_id"])

    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "in_progress", "done", "cancelled",
                    name="status", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("low", "normal", "high", name="priority", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id", "tenant_id"],
            ["sites.id", "sites.tenant_id"],
            name="fk_work_orders_site_same_tenant",
        ),
    )
    op.create_index("ix_work_orders_tenant_id", "work_orders", ["tenant_id"])
    op.create_index("ix_work_orders_site_id", "work_orders", ["site_id"])
    op.create_index("ix_work_orders_tenant_status", "work_orders", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("work_orders")
    op.drop_table("sites")
    op.drop_table("tenants")
