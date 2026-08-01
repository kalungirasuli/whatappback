from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dependencies import get_db
from src.domain.models import User
from src.domain.enums import UserRole
from src.auth.jwt import JWTService

security = HTTPBearer()

jwt_service = JWTService()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = jwt_service.decode_token(credentials.credentials)

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = int(payload.get("sub", 0))
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.is_banned:
        raise HTTPException(status_code=403, detail="Account is banned")

    return user


async def require_client(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != UserRole.client:
        raise HTTPException(status_code=403, detail="Client access required")
    return user


async def require_merchant(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != UserRole.merchant:
        raise HTTPException(status_code=403, detail="Merchant access required")
    return user


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
