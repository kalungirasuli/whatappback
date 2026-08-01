from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dependencies import get_db
from src.core.config import settings
from src.domain.models import Admin
from src.domain.schemas import AdminLoginRequest, AdminTokenResponse
from src.admin.auth import verify_password, create_access_token, get_current_admin, hash_password
from src.admin.routes import merchants, buyers, listings, analytics

app = FastAPI(title="whatAppseller Admin Dashboard", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(merchants.router)
app.include_router(buyers.router)
app.include_router(listings.router)
app.include_router(analytics.router)


@app.post("/admin/login", response_model=AdminTokenResponse)
async def admin_login(req: AdminLoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Admin).where(Admin.email == req.email))
    admin = result.scalar_one_or_none()
    if not admin or not verify_password(req.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")
    admin.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    token = create_access_token(admin.id, admin.email, admin.role)
    return AdminTokenResponse(access_token=token)


@app.post("/admin/seed")
async def seed_admin(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Admin).where(Admin.email == "admin@whatappseller.com"))
    existing = result.scalar_one_or_none()
    if existing:
        return {"message": "Admin already exists", "email": existing.email}
    admin = Admin(
        email="admin@whatappseller.com",
        password_hash=hash_password("changeme123"),
        role="superadmin",
        is_active=True,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return {"message": "Admin created", "email": admin.email, "password": "changeme123", "id": admin.id}


@app.get("/admin/me")
async def get_me(admin=Depends(get_current_admin)):
    return {
        "id": admin.id,
        "email": admin.email,
        "role": admin.role.value,
        "last_login_at": admin.last_login_at.isoformat() if admin.last_login_at else None,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "admin-dashboard"}
