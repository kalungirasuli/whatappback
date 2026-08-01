"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-19

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE merchant_status AS ENUM ('approved', 'suspended', 'banned')")
    op.execute("CREATE TYPE product_status AS ENUM ('pending_moderation', 'active', 'inactive')")
    op.execute("CREATE TYPE moderation_status AS ENUM ('pending', 'passed', 'failed')")
    op.execute("CREATE TYPE message_role AS ENUM ('merchant', 'buyer')")
    op.execute("CREATE TYPE message_direction AS ENUM ('in', 'out')")
    op.execute("CREATE TYPE message_type AS ENUM ('text', 'image', 'template')")
    op.execute("CREATE TYPE interest_status AS ENUM ('sent', 'responded')")
    op.execute("CREATE TYPE moderation_entity_type AS ENUM ('merchant', 'product')")
    op.execute("CREATE TYPE admin_role AS ENUM ('superadmin', 'moderator')")

    op.create_table(
        "admins",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("superadmin", "moderator", name="admin_role", create_type=False),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_admins_email"), "admins", ["email"], unique=True)

    op.create_table(
        "buyers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("is_banned", sa.Boolean(), nullable=False),
        sa.Column("banned_reason", sa.Text(), nullable=True),
        sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_number"),
    )
    op.create_index(op.f("ix_buyers_phone_number"), "buyers", ["phone_number"], unique=True)

    op.create_table(
        "merchants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("business_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("location_lat", sa.Float(), nullable=True),
        sa.Column("location_lng", sa.Float(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("approved", "suspended", "banned", name="merchant_status", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_number"),
    )
    op.create_index(op.f("ix_merchants_phone_number"), "merchants", ["phone_number"], unique=True)

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("stock_qty", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("pending_moderation", "active", "inactive", name="product_status", create_type=False),
            nullable=False,
        ),
        sa.Column("qdrant_point_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_products_merchant_id"), "products", ["merchant_id"])

    op.create_table(
        "product_images",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("storage_url", sa.String(length=500), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column(
            "moderation_status",
            postgresql.ENUM("pending", "passed", "failed", name="moderation_status", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_product_images_product_id"), "product_images", ["product_id"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("merchant", "buyer", name="message_role", create_type=False),
            nullable=False,
        ),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id"), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("whatsapp_window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_phone_number"), "conversations", ["phone_number"])

    op.create_table(
        "conversation_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column(
            "direction",
            postgresql.ENUM("in", "out", name="message_direction", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "message_type",
            postgresql.ENUM("text", "image", "template", name="message_type", create_type=False),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversation_logs_phone_number"), "conversation_logs", ["phone_number"])

    op.create_table(
        "interest_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("buyer_phone", sa.String(length=20), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("sent", "responded", name="interest_status", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_interest_events_buyer_phone"), "interest_events", ["buyer_phone"])

    op.create_table(
        "moderation_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "entity_type",
            postgresql.ENUM("merchant", "product", name="moderation_entity_type", create_type=False),
            nullable=False,
        ),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "passed", "failed", name="moderation_status", create_type=False),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("moderation_queue")
    op.drop_table("interest_events")
    op.drop_table("conversation_logs")
    op.drop_table("conversations")
    op.drop_table("product_images")
    op.drop_table("products")
    op.drop_table("merchants")
    op.drop_table("buyers")
    op.drop_table("admins")

    op.execute("DROP TYPE IF EXISTS admin_role")
    op.execute("DROP TYPE IF EXISTS moderation_entity_type")
    op.execute("DROP TYPE IF EXISTS interest_status")
    op.execute("DROP TYPE IF EXISTS message_type")
    op.execute("DROP TYPE IF EXISTS message_direction")
    op.execute("DROP TYPE IF EXISTS message_role")
    op.execute("DROP TYPE IF EXISTS moderation_status")
    op.execute("DROP TYPE IF EXISTS product_status")
    op.execute("DROP TYPE IF EXISTS merchant_status")
