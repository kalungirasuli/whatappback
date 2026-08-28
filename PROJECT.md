# whatAppSeller — Project Overview

> An AI-powered visual-search marketplace for Uganda, delivered through a **web app (whatApp)** with WhatsApp as a companion channel.

---

## 1. What Is This Project?

**whatAppSeller** is a two-sided marketplace for buyers and merchants. It has **two channels that share one backend**:

1. **whatApp — the web interface (primary).** A React app that looks and feels like a WhatsApp conversation. Buyers chat with "Lisa", the AI shopping assistant, send photos or text, and get ranked products as rich cards with images, prices, and seller details. Merchants manage their shops and catalogs through a dedicated dashboard with analytics, and admins run the whole platform through a full admin console.
2. **WhatsApp Business API (companion channel).** The same AI and catalog, reachable through an ordinary WhatsApp number via text commands (`@register`, `@post`, `@stock`, …) and webhook-driven message processing.

A buyer sends a photo or a short text description of what they want, and the system — powered by AI visual search — returns ranked, in-stock products from nearby merchants. The name captures the idea: a **seller** that lives inside a **WhatsApp-style experience**.

### One-liner

> "Point your camera at what you want — or just describe it — and get real products from real nearby shops, ranked by how well they match — from your browser or straight from WhatsApp."

---

## 2. Two Channels, One Backend

| | **whatApp (Web app)** | **WhatsApp channel** |
|---|---|---|
| Interface | React + Vite + Tailwind, installable as a PWA | Native WhatsApp chat |
| Access | Any browser; add-to-home-screen; works offline | Any phone number |
| Auth | WhatsApp OTP verification → JWT tokens | Phone number = identity |
| Buyer | Chat with Lisa (text/photo) → rich product cards → "I'm interested" | Photo/text messages → ranked results → tap interest |
| Merchant | **Shop dashboard with analytics** (overview, category insight, products, buyers, recommendations), product manager, shop registration | `@register` / `@post` / `@edit` / `@stock` / `@price` / `@delete` / `@help` commands |
| Admin | **Full admin console** (overview, users, merchants & products, chat interactions, interest events, analytics, admin accounts) | — (web only) |

**Design principle:** WhatsApp Business API charges per conversation, so the web app is the **frontend-first primary channel** (richer, cheaper, no per-message cost), while WhatsApp remains a familiar fallback and notification channel. The phone number is the single identity across both — a merchant who registers in the web app has the same shop in WhatsApp, and vice versa.

---

## 3. The Problem It Solves

### In Uganda (and most of East Africa):

- **WhatsApp is the de-facto commerce channel.** Buyers and sellers already transact there informally — sending photos back and forth, asking "do you have X?", sharing catalog images in statuses and groups.
- **There is no central marketplace.** A buyer wanting "red Nike sneakers under 150k" has to contact multiple sellers one by one, resend photos, and compare prices manually.
- **Sellers have no way to be discovered.** Small shops rely on word of mouth and status updates. Their inventory is invisible to anyone who isn't already a contact.
- **Existing marketplaces are a bad fit.** They require app downloads, data, registrations, and structured listing forms that small traders find cumbersome. Trust is also a problem on anonymous platforms.

### The insight

People already trust WhatsApp, already know how to send a photo, and already expect a conversational reply. The marketplace should feel like that familiar chat experience — but delivered through a **purpose-built web app** that isn't limited by WhatsApp's per-conversation costs, media restrictions, or template rules.

---

## 4. Why It Was Developed

The project was built to prove that AI visual search can turn a chat thread into a real commerce engine, and that it can do so at sustainable cost:

1. **Web-first, WhatsApp-second.** WhatsApp Business API charges per conversation, so the system's **main interface is the whatApp web app** (React, installable as a PWA). It gives a rich, unlimited, cheaper experience — chat, product cards, dashboards, analytics — while WhatsApp remains a low-friction fallback for users who never leave their messaging app.
2. **Zero-install experience** — a phone number (verified by WhatsApp OTP) and a browser are the entire onboarding; the PWA can be added to the home screen in one tap.
3. **Natural, conversational discovery** — the AI sales agent ("Lisa") understands free text and images, asks for what it needs, and talks back like a person, not a form.
4. **Low barrier for merchants** — catalog management via WhatsApp commands **or** a full web shop manager with analytics and recommendations for power users.
5. **Nearby-first matching** — a buyer searching from Kampala sees products from Kampala first, using location-aware ranking.
6. **Single identity, two channels** — the same `users` table and phone-number identity drive the web app (JWT) and WhatsApp (webhook), so a shop is one shop everywhere.

---

## 5. Goals — What We Plan to Achieve

### Primary goals

| Goal | Description |
|------|-------------|
| **Web-first experience** | whatApp is the primary, richest interface: conversational search UI, product cards, merchant analytics, and a full admin console — installable as a PWA and usable offline. |
| **Accurate visual search** | Photos → object detection → embeddings → vector search → a short, ranked, relevant product list. |
| **Conversational AI** | "Lisa" decides whether to chat or search, presents results conversationally, recalls previous searches by code, and holds context across turns. |
| **Merchant self-service** | Merchants register, post products, and manage stock through the web dashboard **or** WhatsApp commands. |
| **Buyer-to-merchant leads** | "I'm interested" taps generate actionable interest events with the buyer's search context (via an RS- code), notifying merchants. |
| **Merchant intelligence** | Per-shop analytics: impressions, interests, conversion rates, category market insight, top products, buyer lists, and automated recommendations. |
| **Trust & safety** | Automated image moderation, admin tools to suspend/ban bad actors, and full visibility via the admin console. |
| **Dual-channel delivery** | One backend serves the rich web app and the familiar WhatsApp channel. |
| **Monetization path** | Tiered subscription plans (Starter, Growth, Pro, Enterprise) that gate product limits. |

### Non-goals (for now)

- No payments / escrow built in yet — this is a **discovery + lead generation** platform.
- No delivery/logistics integration.
- English + Luganda localization is scoped, English ships first.

---

## 6. Who It's Built For

### Three roles

| Role | Interface | Who they are | What they do |
|------|-----------|--------------|--------------|
| **Client / Buyer** | whatApp web app (primary) + WhatsApp | Anyone with a phone number, a browser, a photo, or an idea | Search by image or text, browse ranked product cards, tap "I'm interested", track interests and search history, chat with Lisa |
| **Merchant** | whatApp web app (shop manager + dashboard + analytics) + WhatsApp (`@commands`) | Small shop owners, phone shops, fashion sellers, car dealers | Register a shop, post/edit products with photos, set prices and stock, watch analytics and recommendations, receive buyer interest leads, subscribe to a plan |
| **Admin** | whatApp admin console (web) + port-8001 admin API | Platform operators | Monitor analytics, inspect chat interactions and interest events, suspend/ban merchants and buyers, moderate listings, manage admin accounts |

### Target market

- Primary: **Uganda** (Kampala first), with the architecture ready for multi-city East Africa.
- Buyers: everyday consumers already shopping over WhatsApp.
- Sellers: informal and semi-formal retailers — phone dealers, car lots, fashion boutiques, electronics shops, food sellers.

---

## 7. Core Features

### The whatApp web interface (all roles)

- **WhatsApp-style chat UI** — familiar conversation layout with Lisa, quick-action chips ("Find a car", "Latest phones", "Browse shoes", "Upload a photo"), typing indicator, message status, and unread-count scroll-to-bottom.
- **Rich product cards** — search results render as a highlighted **Closest Match** card plus a grid of related products, each with image, name, merchant, price, badges, and an "I'm interested" button.
- **Installable PWA** — add to home screen, works offline via service worker caching, standalone display mode.
- **Guest browsing** — chat with Lisa before creating an account; interests/history unlock after phone verification.
- **History & interests modal** — browse past conversations, saved searches, and remove interests.
- **Guest-to-account continuity** — a guest chat is preserved and linked when an account is created.

### For buyers
- **Photo search** — upload a picture; YOLO detects and crops the object, SigLIP + DINOv2 create embeddings, Qdrant returns the closest matches.
- **Text / natural-language search** — "red Nike sneakers under 150k" is parsed into intents and entities, then searched.
- **Conversational chat** — greet, ask for help, describe, upload, refine, and recall previous results ("my last search").
- **RS- result codes** — every search produces a shareable code (`RS-A3K2`) a buyer can give a merchant to show exactly what they want.
- **Location-aware ranking** — results are boosted if the seller is within ~10 km.
- **Express interest** — tap "I'm interested" on any product; the merchant is notified, and the buyer sees the seller's full contact details in chat.

### For merchants
- **Shop registration & shop list** — open a shop in a guided form; manage multiple shops per account.
- **Shop manager (web)** — full product CRUD with photo upload/removal, price, stock, category, and attributes — the web counterpart of the `@post`/`@edit`/`@delete` commands.
- **Business dashboard with analytics** (7/30/90-day windows):
  - **Overview** — products, active products, interests, unique buyers, search impressions, conversion rate, average match score, and a timeline chart.
  - **Category insight** — market share vs. competition in the merchant's category, attribute demand, and price benchmarking.
  - **Products** — per-product impressions, interests, conversion, average score and rank.
  - **Buyers** — who's interested, first/last seen, which products they engage with.
  - **Recommendations** — automated, prioritized action suggestions.
- **WhatsApp `@commands`** — `@register`, `@post`, `@edit`, `@stock`, `@price`, `@delete`, `@help`.
- **Result-code lookup** — see what a customer wants without exposing the customer's identity.
- **Subscription plans** — Starter (free, 5 products), Growth, Pro, Enterprise.

### For admins
- **Admin console (web)** with seven sections: **Overview**, **Users**, **Merchants & products**, **Chat interactions**, **Interest events**, **Analytics**, and **Admin accounts**.
- **Platform analytics** — conversation volume, top categories, top merchants, reply-type distribution, latency, and daily timelines.
- **Merchant management** — list/detail, suspend, reactivate, ban (ban also deactivates all their products).
- **Buyer/user management** — list/detail, role assignment, ban/unban.
- **Listing moderation** — list/detail, deactivate, reactivate.
- **Conversation inspection** — every chat interaction is logged (input, NLU intents, reply, latency) for debugging and improvement.
- **Standalone admin API (port 8001)** — email/password auth for platform operators who don't use the web console.

---

## 8. Architecture

### High-level diagram

```
                           WhatsApp Business API
                                   │
                 ┌─────────────────┴─────────────────┐
                 │  Webhook Gateway (port 8000)        │
                 │  verify signature → dedupe → queue  │
                 └─────────────────┬──────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│               whatApp — Web Frontend (React + Vite + Tailwind)          │
│                                                                         │
│  Buyer:  AuthGate → ChatWindow (Lisa chat + product cards)              │
│          → ProfileModal, HistoryModal                                   │
│  Merchant: ShopsPage (shop manager) → DashboardPage (analytics,         │
│          recharts) → ShopRegistrationForm                               │
│  Admin:  AdminLayout → Overview / Users / Merchants & products /        │
│          Chat interactions / Interest events / Analytics / Accounts     │
│                                                                         │
│  api.ts → localStorage JWT + auto-refresh → http://localhost:8002       │
│  PWA: service worker (offline cache) + install prompt                   │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │ HTTP (multipart/form-data, JSON)
                                    ▼
                 ┌─────────────────────────────────────┐
                 │        API Gateway (FastAPI)         │
                 │  /api/auth /api/chat /api/products   │
                 │  /api/search /api/clients /api/merch │
                 │  /api/result-codes /api/admin        │
                 └───┬──────────┬──────────┬────────────┘
                     │          │          │
         ┌───────────┴──┐   ┌───┴────┐  ┌─┴────────────┐
         │  PostgreSQL  │   │ Redis  │  │    Qdrant    │
         │  (5433)      │   │ (6380) │  │    (6333)    │
         │  system of   │   │ OTPs,  │  │  vector DB   │
         │  record      │   │ sessions│  │  siglip/dino │
         └───────────┬──┘   └────────┘  │  text (768d) │
                     │                   └──────────────┘
         ┌───────────┴──┐   ┌────────────┐
         │    MinIO     │   │   Ollama   │
         │  images(9000)│   │ gemma2:2b  │
         │              │   │  (11434)   │
         └──────────────┘   └────────────┘

         Standalone Admin API (port 8001) — separate FastAPI app
```

### Frontend architecture (whatApp)

```
whatApp/
├── src/
│   ├── App.tsx              Routing (HashRouter) + global state + chat logic
│   │                        + localStorage persistence + PWA install prompt
│   ├── api.ts               Typed API client: JWT auth, token auto-refresh,
│   │                        guest ID header, JSON + multipart
│   ├── types.ts             Shared TypeScript types for all API domain objects
│   ├── data.ts              Defaults, avatars, timestamps
│   ├── index.css            Tailwind + WhatsApp theme (wa-* colors) + animations
│   ├── components/
│   │   ├── AuthGate.tsx             OTP phone verification (WhatsApp OTP)
│   │   ├── ChatWindow.tsx           Chat layout, welcome screen, quick actions
│   │   ├── ChatHeader.tsx           Header with avatar + role-based menu
│   │   ├── MessageBubble.tsx        Text / image / product-card bubbles
│   │   ├── MessageInput.tsx         Text + file picker + send
│   │   ├── ProductSection.tsx       Closest-match card + related grid
│   │   ├── TypingIndicator.tsx      "Lisa is typing…"
│   │   ├── Sidebar.tsx              Conversation list
│   │   ├── ProfileModal.tsx         User profile editor
│   │   ├── HistoryModal.tsx         Interests + search history
│   │   ├── ShopRegistrationForm.tsx Merchant onboarding
│   │   ├── ShopManagementModal.tsx  Product CRUD with image upload
│   │   ├── MerchantDashboard.tsx    Analytics dashboards (recharts)
│   │   └── FormField.tsx            Reusable form field
│   └── pages/
│       ├── DashboardPage.tsx        Merchant dashboard entry / shop picker
│       ├── ShopsPage.tsx            Shop list + manager
│       └── admin/                   Admin console (7 sections)
```

### Key design decisions

1. **Web app first, WhatsApp as companion.** The whatApp web app is the primary, cost-effective interface; WhatsApp is the fallback/notification channel. Both share one backend and one identity.
2. **Webhook gateway does nothing but verify + enqueue.** All real work happens in queue workers — WhatsApp retries aggressively on slow responses, so synchronous processing under a webhook would lose/duplicate events.
3. **Router precedence (hard rule):** if a sender is in merchant mode and the message matches `@command` grammar, it goes straight to merchant commands — the LLM agent NEVER handles structured data entry.
4. **NLU extractor is permanent, not a throwaway.** A cheap structured extractor classifies intents + entities; the AI agent consumes that output for reply composition instead of re-doing classification.
5. **Hybrid ranking, not hard filtering.** Price/location "nudge" scores instead of excluding near-misses (a buyer's "under 300k" shouldn't hide an item at 310k).
6. **Never show raw similarity %.** Qualitative labels only — "Closest match", "Similar style", "Good alternative" — a trust decision for a word-of-mouth market.
7. **Phone number = identity.** Verified via WhatsApp OTP; JWT access + refresh tokens for the web app, webhook lookup for the WhatsApp channel.
8. **Admin is a third role with its own console.** Full admin pages in the web app (`/admin/*`) backed by `/api/admin`, plus a standalone admin API on port 8001.
9. **Guest-first onboarding.** Users can chat with Lisa and search before creating an account; phone verification unlocks interests, history, and merchant features while preserving the guest conversation.

---

## 9. Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.14 + FastAPI (async) |
| **Frontend** | **React 18 + Vite + TypeScript + Tailwind CSS** (whatApp web app) |
| Frontend UI | WhatsApp-style theme (Tailwind `wa-*` tokens), lucide-react icons, recharts charts |
| PWA | vite-plugin-pwa (service worker, offline cache, install prompt) |
| Object detection | Ultralytics **YOLOv11 Nano** (`yolo11n.pt`) |
| Visual embeddings | **SigLIP** (`google/siglip-base-patch16-224`) + **DINOv2** (`facebook/dinov2-base`), both 768-dim |
| Text embeddings | `all-mpnet-base-v2` (768-dim) |
| Conversational AI | Ollama **`gemma2:2b`** ("Lisa" agent) |
| Vector database | **Qdrant** (payload-filtered ANN, hybrid siglip+dinov2) |
| Relational DB | **PostgreSQL + PostGIS** (system of record, geo queries) |
| Session store | **Redis** (OTP, sessions, chat history, search context) |
| Object storage | **MinIO** (S3-compatible) for product/search images |
| WhatsApp | WhatsApp Business Cloud API (webhook + OTP + notifications) |
| Migrations | Alembic |
| Orchestration | Docker Compose (one Dockerfile per service) |
| Tests | pytest — **513 tests, all passing** |

### ML model sizes (auto-downloaded on first use)

| Model | Size | Use |
|-------|------|-----|
| YOLOv11n | ~6 MB | Object detection & cropping |
| SigLIP | ~350 MB | Primary image embedding |
| DINOv2 | ~450 MB | Fine-grained visual similarity |
| Gemma2:2b | ~1.6 GB | Lisa conversational agent |

---

## 10. Data Model (core tables)

```
users                  — unified identity (phone = PK-ish), role (client|merchant|admin)
merchants              — business profile, category, location, status (approved|suspended|banned)
products               — catalog items, price, stock, status, qdrant_point_id
product_images         — images with moderation_status, is_primary
buyers                 — buyer record, ban state
subscription_plans     — Starter/Growth/Pro/Enterprise tiers
merchant_subscriptions — active plan per merchant
interest_events        — buyer "I'm interested" leads (sent|responded)
result_codes           — RS- codes linking a search to its context
chat_interactions      — every /api/chat turn (input, NLU, reply, latency)
conversation_logs      — raw message log (in/out) for replay & debugging
conversations / conversation_messages — durable chatroom context
customer_memory        — long-term buyer facts (name, budget, preferences)
admins                 — admin dashboard accounts (email/password, role)
moderation_queue       — pending moderation entities
```

---

## 11. Key User Flows

### Buyer flow (whatApp web app)
1. Open the app — chat with Lisa as a **guest** (no signup required).
2. Send a photo or "I need red Nike sneakers under 150k".
3. YOLO detects the object → SigLIP/DINOv2 embed → Qdrant search → reranker ranks by relevance + price + proximity.
4. Lisa presents a ranked list with a "Closest match" highlighted card, images, prices, and merchant names.
5. Create an account with phone + OTP → tap **"I'm interested"** on any product → interest event created → merchant notified (respecting WhatsApp's 24h window).
6. Track interests and search history in the History modal; optionally share the **RS- code** so a merchant sees exactly what was searched.
7. As a PWA, the app is installed to the home screen and works offline.

### Buyer flow (WhatsApp channel)
Same search intelligence over WhatsApp messages: send a photo or text, receive a ranked result list, tap interest, receive merchant responses.

### Merchant flow (whatApp web app)
1. Sign in with phone + OTP → create a shop via the guided registration form.
2. Add products with photos, prices, and stock in the shop manager (web CRUD; images moderated and indexed automatically).
3. Open the **dashboard** for analytics: impressions, interests, conversion rate, category insight, top products, buyer list, and recommendations.
4. Receive interest leads and follow up with buyers directly.

### Merchant flow (WhatsApp channel)
1. `@register` → wizard (business name → category → location) → active immediately.
2. `@post` + image + caption → image moderated, stored in MinIO, indexed to Qdrant.
3. `@price 12 850000`, `@stock 12 40`, `@edit ...` — manage live.
4. Receives interest notifications when buyers engage with their products.

### Admin flow (whatApp admin console)
1. Log in with an admin-role account (created via `POST /api/admin/bootstrap`).
2. View the **Overview** dashboard with platform-wide counts and recent activity.
3. Inspect **chat interactions** (full NLU + reply + latency detail) and **interest events**.
4. Manage **users**, **merchants & products** (suspend/reactivate/ban, deactivate/reactivate listings).
5. Review **analytics** (daily timelines, top merchants/categories, reply-type distribution).
6. Manage **admin accounts**. (Platform operators can also use the standalone admin API on port 8001.)

---

## 12. The AI Search Pipeline (in one paragraph)

An uploaded image is run through **YOLO object detection** to isolate the product from background clutter (with a center-crop fallback when confidence is low). The primary crop is embedded twice — **SigLIP** for the image+text joint semantic space and **DINOv2** for fine-grained visual similarity — plus the product name/brand/category as a text vector. Qdrant runs a **hybrid search** (0.6 × SigLIP + 0.4 × DINOv2), then a **business-rule reranker** nudges scores for text matches, price proximity, and seller distance. A **consistency filter** keeps only results in the same product family as the detected object, and Lisa presents the final ranked list conversationally with qualitative match labels.

---

## 13. Repository Layout

```
whatAppseller/                    ← backend + admin (this repo)
├── src/
│   ├── api/            FastAPI app (port 8002) + routes
│   │   └── routes/     chat, products, search, clients, merchants,
│   │                   nlu, result_codes, analytics, admin
│   ├── admin/          Standalone admin dashboard app (port 8001)
│   │   └── routes/     merchants, buyers, listings, analytics
│   ├── auth/           OTP + JWT authentication
│   ├── core/           config, dependencies
│   ├── domain/         SQLAlchemy models, Pydantic schemas, enums
│   ├── services/       detector, embedding, qdrant, reranker,
│   │                   lisa_agent, ocr, categories, object_storage,
│   │                   chat_log_service, result_code_service
│   ├── workers/        search_pipeline, vision_pipeline, nlu_router, router
│   └── shared/         logging, reqlog
├── migrations/         Alembic migrations
├── tests/              513 tests across admin, auth, search, pipeline, etc.
├── scripts/            eval, reindex, seed, reset scripts
├── docker/             docker-compose.yml + Dockerfiles
├── postman_collection.json  Full REST API collection
└── PROJECT.md          ← you are here

whatApp/                          ← web frontend (sibling repo)
├── src/
│   ├── App.tsx          Routing + global state + chat logic + PWA
│   ├── api.ts           Typed API client (JWT auto-refresh, multipart)
│   ├── components/      ChatWindow, MessageBubble, ProductSection,
│   │                    AuthGate, MerchantDashboard, ShopManagementModal,
│   │                    ProfileModal, HistoryModal, ...
│   └── pages/           DashboardPage, ShopsPage, admin/ (admin console)
├── index.html / vite.config.ts / tailwind.config.js / package.json
└── public/              PWA icons + manifest
```

Related docs: `ARCHITECTURE.md` (deep technical pipeline), `PLAN.md` (implementation plan + design decisions), `PLAN_DUAL_CHANNEL.md` (web + WhatsApp dual-channel design), `setup.md` (dev setup), `STEPS.md` (build progress).

---

## 14. How to Run It

### Requirements
Python 3.14+, Node.js 18+, Docker Desktop, Ollama, NVIDIA GPU (6 GB VRAM, optional but recommended).

### Quick start (Windows) — backend
```powershell
pip install -r requirements.txt
make docker-up                  # Postgres, Redis, Qdrant, MinIO
alembic upgrade head            # migrate the database
ollama pull gemma2:2b           # Lisa's brain
uvicorn src.api.main:app --port 8002 --reload
```
Or all-in-one: `./start.ps1` (Docker + migrations + API + webhook + worker); `./stop.ps1` to stop.

### Quick start — whatApp web frontend
```bash
cd ../whatApp
npm install
npm run dev                     # Vite dev server (default http://localhost:5173)
npm run build                   # production build
npm run preview                 # preview the production build
```
The frontend calls the backend at `http://localhost:8002` (override with `VITE_API_URL`). It is a PWA — after a production build, install it to the home screen for the offline experience.

### Ports
| Service | Port |
|---------|------|
| PostgreSQL | 5433 |
| Redis | 6380 |
| Qdrant | 6333/6334 |
| MinIO | 9000/9001 |
| Webhook gateway | 8000 |
| Admin dashboard API | 8001 |
| REST API | 8002 |
| whatApp dev server (Vite) | 5173 |

### Testing
```bash
pytest              # 513 backend tests
cd ../whatApp
npm run lint        # frontend lint
```

---

## 15. Current Status

All three phases are implemented and tested (see `STEPS.md`):

- **Phase 1 — Foundations:** webhook gateway, rate limiting, merchant `@register`/`@post`, WhatsApp client, logging. ✅
- **Phase 2 — AI pipeline:** YOLO crop, SigLIP/DINOv2 embeddings, Qdrant indexing, buyer image + text search, NLU extractor, E2E flow. ✅
- **Phase 3 — Production & AI agent:** Lisa conversational agent, notification service, PostGIS, full merchant command set, admin API + auth + analytics, cost tracking, Uganda DPA compliance pass. ✅
- **whatApp web app (primary interface):** React + Vite + Tailwind frontend with buyer chat (Lisa + product cards), merchant shop manager + analytics dashboard, full admin console, PWA installability, guest-first onboarding, JWT auto-refresh. ✅
- **Dual channel:** unified `users` table, WhatsApp OTP + JWT, full REST API consumed by the frontend, WhatsApp webhook still backward compatible. ✅

### Known remaining work
- **Full NSFW moderation model** — a format/header moderation stub is active; the full NSFW model is deferred to the deployment environment (needs GPU + model download).
- **Docker image verification** — PostGIS + MinIO images need pulling when bandwidth allows.
- **Live integration testing** — end-to-end test with a real WhatsApp sandbox.
- **WhatsApp template approval** from Meta (required for outbound messages outside the 24h window).
- **Payments/escrow and delivery** are future phases.

---

## 16. Security & Compliance

- JWT access tokens (short-lived) + refresh tokens (30 days, revocable in Redis) for the web API and the whatApp frontend; separate JWT for the standalone admin dashboard.
- Frontend token handling with automatic silent refresh on 401 and full session cleanup on logout.
- OTP verification with rate limiting (3 per phone per 15 minutes) — verifies the phone actually belongs to the user.
- WhatsApp webhook signature verification + message-ID deduplication for idempotency.
- Per-phone / per-IP rate limiting on inbound handling.
- Admin-only moderation (suspend/ban) enforced via role checks at the API layer.
- **Uganda Data Protection & Privacy Act (2019)** compliance pass: phone-number and GPS data handling, consent, and retention (see `src/shared/compliance.py` in the plan).
- Images go through a moderation gate before being indexed and made searchable.

---

## 17. How to Contribute / Explore

1. Read `ARCHITECTURE.md` for the full chat and indexing pipeline.
2. Read `PLAN.md` for the roadmap and the "hard" design decisions.
3. Read `PLAN_DUAL_CHANNEL.md` for the web + WhatsApp dual-channel design rationale.
4. Run the whatApp frontend (`cd ../whatApp && npm run dev`) against a local backend, or use the Postman collection (`postman_collection.json`) for full client, merchant, and admin API workflows.
5. Run `pytest` and the evaluation harness in `scripts/` (`eval_accuracy.py`, `test_image_accuracy.py`) to measure search quality.
