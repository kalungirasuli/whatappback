import datetime

from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB

from src.domain.enums import (
    MerchantStatus,
    ProductStatus,
    ModerationStatus,
    MessageRole,
    MessageDirection,
    MessageType,
    InterestStatus,
    ModerationEntityType,
    AdminRole,
    SubscriptionStatus,
    PlanSlug,
    UserRole,
)


class Base(DeclarativeBase):
    pass


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[MerchantStatus] = mapped_column(
        PG_ENUM(MerchantStatus, name="merchant_status", create_type=False),
        default=MerchantStatus.approved,
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )

    products: Mapped[list["Product"]] = relationship("Product", back_populates="merchant")
    conversations: Mapped[list["Conversation"]] = relationship("Conversation", back_populates="merchant")
    subscriptions: Mapped[list["MerchantSubscription"]] = relationship(
        "MerchantSubscription", back_populates="merchant"
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(Integer, ForeignKey("merchants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="UGX", nullable=False)
    stock_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ProductStatus] = mapped_column(
        PG_ENUM(ProductStatus, name="product_status", create_type=False),
        default=ProductStatus.active,
        nullable=False,
    )
    qdrant_point_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), onupdate=datetime.datetime.now(datetime.UTC), nullable=False
    )

    merchant: Mapped[Merchant] = relationship("Merchant", back_populates="products")
    images: Mapped[list["ProductImage"]] = relationship("ProductImage", back_populates="product")


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    storage_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        PG_ENUM(ModerationStatus, name="moderation_status", create_type=False),
        default=ModerationStatus.pending,
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )

    product: Mapped[Product] = relationship("Product", back_populates="images")


class Buyer(Base):
    __tablename__ = "buyers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    banned_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    banned_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )
    last_active_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    role: Mapped[MessageRole] = mapped_column(
        PG_ENUM(MessageRole, name="message_role", create_type=False), nullable=False
    )
    merchant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("merchants.id"), nullable=True
    )
    last_message_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )
    whatsapp_window_expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    merchant: Mapped[Merchant | None] = relationship("Merchant", back_populates="conversations")


class ConversationLog(Base):
    __tablename__ = "conversation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    direction: Mapped[MessageDirection] = mapped_column(
        PG_ENUM(MessageDirection, name="message_direction", create_type=False), nullable=False
    )
    message_type: Mapped[MessageType] = mapped_column(
        PG_ENUM(MessageType, name="message_type", create_type=False), nullable=False
    )
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )


class InterestEvent(Base):
    __tablename__ = "interest_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    buyer_phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    merchant_id: Mapped[int] = mapped_column(Integer, ForeignKey("merchants.id"), nullable=False)
    status: Mapped[InterestStatus] = mapped_column(
        PG_ENUM(InterestStatus, name="interest_status", create_type=False),
        default=InterestStatus.sent,
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )

    product: Mapped["Product"] = relationship("Product")
    merchant: Mapped["Merchant"] = relationship("Merchant")


class ModerationQueue(Base):
    __tablename__ = "moderation_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[ModerationEntityType] = mapped_column(
        PG_ENUM(ModerationEntityType, name="moderation_entity_type", create_type=False), nullable=False
    )
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ModerationStatus] = mapped_column(
        PG_ENUM(ModerationStatus, name="moderation_status", create_type=False),
        default=ModerationStatus.pending,
        nullable=False,
    )
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("admins.id"), nullable=True)
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[AdminRole] = mapped_column(
        PG_ENUM(AdminRole, name="admin_role", create_type=False),
        default=AdminRole.moderator,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[PlanSlug] = mapped_column(
        PG_ENUM(PlanSlug, name="plan_slug", create_type=False), nullable=False, unique=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="UGX", nullable=False)
    max_products: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_images_per_product: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    features: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )

    subscriptions: Mapped[list["MerchantSubscription"]] = relationship(
        "MerchantSubscription", back_populates="plan"
    )


class MerchantSubscription(Base):
    __tablename__ = "merchant_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(Integer, ForeignKey("merchants.id"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("subscription_plans.id"), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        PG_ENUM(SubscriptionStatus, name="subscription_status", create_type=False),
        default=SubscriptionStatus.active,
        nullable=False,
    )
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC),
        onupdate=datetime.datetime.now(datetime.UTC), nullable=False
    )

    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="subscriptions")
    plan: Mapped["SubscriptionPlan"] = relationship("SubscriptionPlan", back_populates="subscriptions")


class ResultCode(Base):
    __tablename__ = "result_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    product_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sample_products: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )


class ChatInteraction(Base):
    """One conversational turn with the retail receptionist (/api/chat).

    Logs the user's message (text and/or image), what the system understood,
    and what the system replied — used to improve the assistant over time.
    """

    __tablename__ = "chat_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_message_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    user_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    nlu_intents: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    text_topic: Mapped[str | None] = mapped_column(String(100), nullable=True)
    text_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    image_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reply_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_code: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    follow_up: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    top_results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        PG_ENUM(UserRole, name="user_role", create_type=False),
        default=UserRole.client,
        nullable=False,
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )
    last_active_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.now(datetime.UTC), nullable=False
    )
