from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.dependencies import get_db
from src.domain.models import Admin
from src.domain.enums import AdminRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(admin_id: int, email: str, role: AdminRole) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.admin_session_expire_hours)
    return jwt.encode(
        {"sub": str(admin_id), "email": email, "role": role.value, "exp": expire},
        settings.admin_jwt_secret,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.admin_jwt_secret, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Admin:
    payload = decode_token(credentials.credentials)
    admin_id = int(payload.get("sub", 0))
    result = await db.execute(select(Admin).where(Admin.id == admin_id, Admin.is_active == True))
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=401, detail="Admin not found or inactive")
    admin.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return admin
