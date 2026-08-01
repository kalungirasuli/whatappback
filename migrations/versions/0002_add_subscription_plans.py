"""add subscription plans

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create plan_slug enum
    plan_slug_enum = postgresql.ENUM("starter", "growth", "pro", "enterprise", name="plan_slug", create_type=False)
    plan_slug_enum.create(op.get_bind(), checkfirst=True)

    # Create subscription_status enum
    sub_status_enum = postgresql.ENUM("active", "expired", "cancelled", name="subscription_status", create_type=False)
    sub_status_enum.create(op.get_bind(), checkfirst=True)

    # subscription_plans table
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", postgresql.ENUM("starter", "growth", "pro", "enterprise", name="plan_slug", create_type=False), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="UGX"),
        sa.Column("max_products", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_images_per_product", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("features", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # merchant_subscriptions table
    op.create_table(
        "merchant_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id"), nullable=False, index=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("subscription_plans.id"), nullable=False),
        sa.Column("status", postgresql.ENUM("active", "expired", "cancelled", name="subscription_status", create_type=False), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Seed default plans
    op.execute("""
        INSERT INTO subscription_plans (name, slug, description, price, currency, max_products, max_images_per_product, features, is_active, sort_order)
        VALUES
            ('Starter', 'starter', 'Perfect for new sellers. Get started with a basic shop.', 0, 'UGX', 5, 1, '["basic_search_listing", "whatsapp_support"]', true, 1),
            ('Growth', 'growth', 'For growing businesses. More products, more visibility.', 50000, 'UGX', 50, 3, '["priority_search", "whatsapp_support", "analytics_basic"]', true, 2),
            ('Pro', 'pro', 'For serious sellers. Unlimited products, featured listings.', 150000, 'UGX', 500, 5, '["featured_listing", "analytics_advanced", "whatsapp_support", "priority_support"]', true, 3),
            ('Enterprise', 'enterprise', 'For large operations. Everything unlimited, API access.', 500000, 'UGX', 999999, 10, '["unlimited", "api_access", "custom_branding", "dedicated_support"]', true, 4)
    """)


def downgrade() -> None:
    op.drop_table("merchant_subscriptions")
    op.drop_table("subscription_plans")
    postgresql.ENUM(name="subscription_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="plan_slug").drop(op.get_bind(), checkfirst=True)
