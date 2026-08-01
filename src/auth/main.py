import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dependencies import get_db, get_redis
from src.domain.models import User
from src.domain.enums import UserRole
from src.auth.otp import OTPService
from src.auth.jwt import JWTService
from src.auth.schemas import (
    RequestOTPRequest,
    RequestOTPResponse,
    VerifyOTPRequest,
    VerifyOTPResponse,
    RefreshRequest,
    RefreshResponse,
    UserResponse,
)
from src.auth.dependencies import get_current_user
from src.shared.phone_utils import normalize_phone, validate_phone

router = APIRouter(prefix="/api/auth", tags=["auth"])

otp_service_instance: OTPService | None = None
jwt_service = JWTService()


def _get_otp_service(redis) -> OTPService:
    global otp_service_instance
    if otp_service_instance is None:
        otp_service_instance = OTPService(redis)
    return otp_service_instance


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        phone=user.phone_number,
        name=user.name,
        role=user.role.value,
        is_verified=user.is_verified,
        created_at=user.created_at.isoformat(),
    )


@router.post("/request-otp", response_model=RequestOTPResponse)
async def request_otp(
    req: RequestOTPRequest,
    redis=Depends(get_redis),
):
    phone = normalize_phone(req.phone)
    if not validate_phone(phone):
        raise HTTPException(status_code=400, detail="Invalid phone number format")

    service = _get_otp_service(redis)
    success = await service.generate_and_send(phone)

    if not success:
        raise HTTPException(
            status_code=429,
            detail="Too many OTP requests. Please wait before trying again.",
        )

    return RequestOTPResponse(
        message="OTP sent successfully via WhatsApp",
        expires_in=300,
    )


@router.post("/verify-otp", response_model=VerifyOTPResponse)
async def verify_otp(
    req: VerifyOTPRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    phone = normalize_phone(req.phone)
    if not validate_phone(phone):
        raise HTTPException(status_code=400, detail="Invalid phone number format")

    if len(req.code) != 6 or not req.code.isdigit():
        raise HTTPException(status_code=400, detail="OTP code must be 6 digits")

    allowed_roles = {"client", "merchant"}
    if req.role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Role must be 'client' or 'merchant'")

    service = _get_otp_service(redis)
    verified = await service.verify(phone, req.code)

    if not verified:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP code")

    result = await db.execute(select(User).where(User.phone_number == phone))
    user = result.scalar_one_or_none()

    now = datetime.datetime.now(datetime.timezone.utc)

    if user is None:
        role_enum = UserRole(req.role)
        user = User(
            phone_number=phone,
            name=req.name,
            role=role_enum,
            is_verified=True,
            is_banned=False,
            created_at=now,
            last_active_at=now,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        if user.is_banned:
            raise HTTPException(status_code=403, detail="Account is banned")
        user.is_verified = True
        user.last_active_at = now
        if req.name and not user.name:
            user.name = req.name
        await db.commit()
        await db.refresh(user)

    access_token = jwt_service.create_access_token(user.id, phone, user.role.value)
    refresh_token = jwt_service.create_refresh_token(user.id, phone, user.role.value)
    await jwt_service.store_refresh_token(redis, user.id, refresh_token)

    return VerifyOTPResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=_user_response(user),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    payload = jwt_service.decode_token(req.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = int(payload.get("sub", 0))
    phone = payload.get("phone", "")
    role = payload.get("role", "")

    valid = await jwt_service.is_refresh_token_valid(redis, user_id, req.refresh_token)
    if not valid:
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.is_banned:
        raise HTTPException(status_code=403, detail="Account is banned")

    new_access = jwt_service.create_access_token(user.id, user.phone_number, user.role.value)

    return RefreshResponse(
        access_token=new_access,
        token_type="bearer",
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return _user_response(user)
