"""add conversation context (public_id, summary, messages, customer memory)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("conversations", sa.Column("public_id", sa.String(length=40), nullable=True))
    op.add_column("conversations", sa.Column("summary", sa.Text(), nullable=True))
    op.create_index(op.f("ix_conversations_public_id"), "conversations", ["public_id"], unique=True)

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_messages_conversation_id"),
        "conversation_messages",
        ["conversation_id"],
        unique=False,
    )

    op.create_table(
        "customer_memory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_key", sa.String(length=20), nullable=False),
        sa.Column("memory", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customer_memory_customer_key"), "customer_memory", ["customer_key"], unique=True)


def downgrade() -> None:
    op.drop_table("customer_memory")
    op.drop_table("conversation_messages")
    op.drop_index(op.f("ix_conversations_public_id"), table_name="conversations")
    op.drop_column("conversations", "summary")
    op.drop_column("conversations", "public_id")
    op.drop_column("conversations", "customer_id")