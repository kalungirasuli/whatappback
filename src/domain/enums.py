import enum


class MerchantStatus(str, enum.Enum):
    approved = "approved"
    suspended = "suspended"
    banned = "banned"


class ProductStatus(str, enum.Enum):
    pending_moderation = "pending_moderation"
    active = "active"
    inactive = "inactive"


class ModerationStatus(str, enum.Enum):
    pending = "pending"
    passed = "passed"
    failed = "failed"


class MessageRole(str, enum.Enum):
    merchant = "merchant"
    buyer = "buyer"


class MessageDirection(str, enum.Enum):
    inbound = "in"
    outbound = "out"


class MessageType(str, enum.Enum):
    text = "text"
    image = "image"
    template = "template"


class InterestStatus(str, enum.Enum):
    sent = "sent"
    responded = "responded"


class ModerationEntityType(str, enum.Enum):
    merchant = "merchant"
    product = "product"


class AdminRole(str, enum.Enum):
    superadmin = "superadmin"
    moderator = "moderator"


class QueueJobType(str, enum.Enum):
    incoming_message = "incoming_message"
    process_image = "process_image"
    send_reply = "send_reply"
    moderation_check = "moderation_check"
    notification = "notification"


class WizardStep(str, enum.Enum):
    business_name = "business_name"
    category = "category"
    location = "location"
    confirm = "confirm"
    complete = "complete"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"


class PlanSlug(str, enum.Enum):
    starter = "starter"
    growth = "growth"
    pro = "pro"
    enterprise = "enterprise"


class UserRole(str, enum.Enum):
    client = "client"
    merchant = "merchant"
    admin = "admin"
