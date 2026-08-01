# Dual-Channel Architecture — Web App + WhatsApp

## Problem Statement
WhatsApp Business API charges per-conversation. To reduce costs and give users a richer experience, we're adding a web frontend alongside WhatsApp. Both channels share the same backend.

## Key Design Decisions

1. **Phone number = identity** for all three roles (client, merchant, admin)
2. **WhatsApp OTP** for phone verification (we already have the WhatsApp API)
3. **JWT tokens** for web app auth (access + refresh)
4. **Same backend** serves both WhatsApp webhook and REST API
5. **Frontend-first** for new interactions, WhatsApp as fallback/notification channel

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend App                              │
│         (React/Next.js — Client + Merchant views)               │
└────────────────────────┬────────────────────────────────────────┘
                         │ REST API (JSON)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API Gateway (FastAPI)                         │
│  JWT verify → rate limit → route to service                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Auth API │ │Product   │ │ Search   │ │Merchant  │          │
│  │ (OTP,    │ │CRUD API  │ │ API      │ │Dashboard │          │
│  │  JWT)    │ │          │ │          │ │API       │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────────────┐
│                        │  Shared Backend                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Domain   │ │Services  │ │ Vision   │ │NLU/Search│          │
│  │ Models   │ │(business │ │Pipeline  │ │Pipeline  │          │
│  │          │ │ logic)   │ │          │ │          │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────────────┐
│                        │  Data Layer                             │
│  PostgreSQL │ Qdrant │ Redis │ S3/MinIO │ WhatsApp API          │
└────────────────────────┴────────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────────┐
│                  WhatsApp Gateway (existing)                     │
│  Webhook → Router → @commands / NLU / Search                    │
│  (unchanged — backward compatible)                              │
└─────────────────────────────────────────────────────────────────┘
```

## New Components

### 1. Auth Service (`src/auth/`)

```
src/auth/
├── __init__.py
├── main.py              # FastAPI router for auth endpoints
├── otp.py               # WhatsApp OTP generation, send, verify
├── jwt.py               # JWT create/verify (access + refresh tokens)
├── dependencies.py      # Auth dependencies (get_current_user, role checks)
└── schemas.py           # Request/response schemas for auth
```

### 2. API Gateway (`src/api/`)

```
src/api/
├── __init__.py
├── main.py              # FastAPI app mounting all routers
├── deps.py              # Shared dependencies (db, redis, auth)
├── routes/
│   ├── products.py      # Product CRUD (merchant + public read)
│   ├── search.py        # Image/text search (client)
│   ├── merchants.py     # Merchant dashboard data
│   ├── clients.py       # Client profile, interests, history
│   ├── subscriptions.py # Plan management
│   └── uploads.py       # Image upload handling
└── schemas/
    ├── products.py
    ├── search.py
    └── merchants.py
```

### 3. WhatsApp OTP Service

```python
# src/auth/otp.py

class OTPService:
    async def generate_otp(phone: str) -> str:
        """Generate 6-digit OTP, store in Redis with 5min TTL"""
        otp = "123456"  # In dev; random in prod
        await redis.setex(f"otp:{phone}", 300, otp)
        return otp

    async def send_otp(phone: str) -> bool:
        """Send OTP via WhatsApp message"""
        otp = await self.generate_otp(phone)
        await send_text(phone, f"Your whatAppseller verification code is: {otp}\n\nThis code expires in 5 minutes.")
        return True

    async def verify_otp(phone: str, code: str) -> bool:
        """Verify OTP against Redis"""
        stored = await redis.get(f"otp:{phone}")
        if stored and stored == code:
            await redis.delete(f"otp:{phone}")
            return True
        return False
```

### 4. JWT Auth (Unified)

```python
# src/auth/jwt.py

# Token payload for ALL roles:
{
    "sub": "123",           # User ID
    "phone": "+256700123456",
    "role": "client",       # client | merchant | admin
    "type": "access",       # access | refresh
    "exp": ...,
    "iat": ...
}

# Access token: 15 minutes
# Refresh token: 30 days
```

### 5. API Endpoints

#### Auth
```
POST /api/auth/request-otp    { phone: "+256700123456" }
POST /api/auth/verify-otp     { phone, code, role?: "client"|"merchant" }
POST /api/auth/refresh        { refresh_token }
GET  /api/auth/me             (requires JWT)
```

#### Products (Merchant)
```
GET    /api/products                    # List merchant's products
POST   /api/products                    # Create product (name, price, category, images)
PUT    /api/products/{id}               # Update product
DELETE /api/products/{id}               # Delete product
POST   /api/products/{id}/images        # Upload additional images
DELETE /api/products/{id}/images/{img_id}
```

#### Search (Client)
```
POST /api/search/image                  # Search by image (multipart)
POST /api/search/text                   # Search by text
GET  /api/search/nearby?lat=&lng=&km=   # Nearby products
```

#### Client
```
GET    /api/client/profile              # Get client profile
PUT    /api/client/profile              # Update profile
GET    /api/client/interests            # List interests
POST   /api/client/interests/{product_id}  # Express interest
DELETE /api/client/interests/{product_id}  # Remove interest
```

#### Merchant
```
GET  /api/merchant/dashboard            # Stats (products, views, interests)
GET  /api/merchant/subscription         # Current plan
POST /api/merchant/subscription         # Change plan
```

#### Admin (existing, minor updates)
```
GET  /api/admin/merchants               # List all merchants
PUT  /api/admin/merchants/{id}/suspend  # Suspend merchant
... (existing endpoints)
```

## Implementation Phases

### Phase A — Auth Foundation (Build First)

**Step A.1**: Add `UserRole` enum and `User` model (unified identity table)

```python
class UserRole(str, enum.Enum):
    client = "client"
    merchant = "merchant"
    admin = "admin"

class User(Base):
    __tablename__ = "users"
    id, phone_number (unique), role, is_verified, is_banned,
    created_at, last_active_at
    # Plus optional fields: name, email (for admin), avatar_url
```

**Step A.2**: WhatsApp OTP service
- Generate 6-digit code → store in Redis (5min TTL) → send via WhatsApp
- Verify endpoint checks Redis, returns JWT pair
- Rate limit: 3 OTPs per phone per 15 minutes

**Step A.3**: JWT auth (access + refresh tokens)
- Access token: 15min, contains user_id + phone + role
- Refresh token: 30 days, stored in Redis for revocation
- Unified `get_current_user()` dependency for all roles

**Step A.4**: Auth API endpoints
- `POST /api/auth/request-otp` — sends WhatsApp OTP
- `POST /api/auth/verify-otp` — verifies OTP, creates user if new, returns JWT
- `POST /api/auth/refresh` — refresh access token
- `GET /api/auth/me` — current user info

### Phase B — REST API (Core Features)

**Step B.1**: Product CRUD API
- Create/update/delete products (merchant only)
- Image upload endpoint (multipart/form-data)
- Public read endpoint for browsing

**Step B.2**: Search API
- Image search (multipart upload → pipeline)
- Text search (JSON body → pipeline)
- Nearby search (lat/lng → PostGIS)

**Step B.3**: Client API
- Profile management
- Interest/wishlist
- Search history

**Step B.4**: Merchant Dashboard API
- Stats (product count, interest count, views)
- Subscription management

### Phase C — Frontend App

**Step C.1**: Project setup
- React/Next.js with TypeScript
- Tailwind CSS
- Auth context (JWT storage, auto-refresh)

**Step C.2**: Client pages
- Browse/search products
- Product detail view
- Express interest
- Profile

**Step C.3**: Merchant pages
- Dashboard (stats)
- Product management (CRUD)
- Subscription plans

**Step C.4**: Admin pages (migrate existing)
- Already built in FastAPI, just needs API integration

## Migration Path for Existing WhatsApp Users

1. When a WhatsApp user first sends a message, check if they have a `users` record
2. If not, auto-create with `is_verified=False`
3. When they want to use the web app, they go through OTP verification
4. Their phone number links their WhatsApp identity to their web identity

## What Stays the Same

- **WhatsApp webhook gateway** — unchanged, backward compatible
- **Worker/router** — unchanged, processes WhatsApp messages
- **Domain models** — unchanged (merchants, products, buyers, subscriptions)
- **Business logic** — unchanged (search, NLU, vision pipeline)
- **Admin dashboard** — unchanged, just add phone-based login option

## What Changes

- **New**: `users` table (unified identity)
- **New**: Auth API (OTP + JWT)
- **New**: REST API endpoints
- **New**: Frontend app
- **Updated**: `merchants` table gets `user_id` FK
- **Updated**: `buyers` table gets `user_id` FK
- **Updated**: Admin auth supports phone + password
