from pydantic import BaseModel


class RequestOTPRequest(BaseModel):
    phone: str


class RequestOTPResponse(BaseModel):
    message: str
    expires_in: int


class VerifyOTPRequest(BaseModel):
    phone: str
    code: str
    role: str = "client"
    name: str | None = None


class UserResponse(BaseModel):
    id: int
    phone: str
    name: str | None
    role: str
    is_verified: bool
    created_at: str


class VerifyOTPResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
