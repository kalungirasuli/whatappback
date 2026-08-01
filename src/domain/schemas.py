from pydantic import BaseModel, Field


class WhatsAppWebhookEntry(BaseModel):
    object: str
    entry: list[dict]


class WhatsAppMessage(BaseModel):
    from_number: str = Field(alias="from")
    id: str
    timestamp: str
    type: str
    text: dict | None = None
    image: dict | None = None


class WhatsAppWebhookPayload(BaseModel):
    entry: list[dict]


class MerchantRegisterRequest(BaseModel):
    phone_number: str
    business_name: str
    category: str
    location_lat: float | None = None
    location_lng: float | None = None


class ProductCreateRequest(BaseModel):
    merchant_id: int
    name: str
    brand: str | None = None
    category: str
    price: float
    currency: str = "UGX"
    stock_qty: int = 0


class ProductUpdateRequest(BaseModel):
    name: str | None = None
    brand: str | None = None
    category: str | None = None
    price: float | None = None
    currency: str | None = None
    stock_qty: int | None = None


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    success: bool = True
    message: str
