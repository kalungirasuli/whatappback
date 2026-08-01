# Implementation Plan — WhatsApp AI Visual Search Marketplace

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   WhatsApp Business Cloud API                    │
└────────────────────────┬────────────────────────────────────────┘
                         │ (Webhook)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Webhook Gateway (FastAPI)                       │
│  verify X-Hub-Signature-256 → dedupe (msg_id) → enqueue → 200   │
│  ** rate-limited per-phone and per-IP (Phase 1) **              │
└────────────────────────┬────────────────────────────────────────┘
                         │ (Message Queue — SQS/RabbitMQ/BullMQ)   │
                         ▼
┌────────────────────────────────────────────────────────────┐
│                     Main Router                              │
│  [1] If sender in merchant mode AND msg matches @command    │
│      → route to merchant_commands.py directly               │
│      → NEVER touches LLM agent                             │
│  [2] If buyer text/image → route to NLU router              │
│      (cheap structural extractor: intent + entities)        │
│  [3] If buyer/merchant free-text outside grammar → LLM     │
│      agent for reply composition                            │
└────────────────────┬───────────────────────────────────────┘
                         │
                         ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────┐
│ Vision       │  │ NLU/Query    │  │ Notification │  │ Moderation│
│ Pipeline     │  │ Router       │  │ Service      │  │ Service   │
│              │  │ (cheap,      │  │              │  │           │
│ crop → embed │  │  structured) │  │ 24h window   │  │ NSFW      │
│ SigLIP +     │  │ intent cls → │  │ check →      │  │ check →   │
│ DINOv2       │  │ entity ext → │  │ send reply   │  │ approve   │
└──────┬───────┘  │ filter merge │  └──────┬───────┘  └─────┬─────┘
                   └──────┬───────┘         │                │
       │                  │                  │                │
       └──────────────────┼──────────────────┼────────────────┘
                          ▼                  │
┌────────────────────────────────────────┐   │
│            Data Layer                   │   │
│  ┌──────────┐ ┌──────────────┐         │   │
│  │ Qdrant   │ │ PostgreSQL + │         │   │
│  │ (vectors │ │ PostGIS      │         │   │
│  │ +filter  │ │ (system of   │         │   │
│  │ payload) │ │ record, geo) │         │   │
│  ├──────────┤ ├──────────────┤         │   │
│  │ Redis    │ │ S3 + CDN     │         │   │
│  │ (session │ │ (images)     │         │   │
│  │ state)   │ │              │         │   │
│  └──────────┘ └──────────────┘         │   │
└────────────────────────────────────────┘   │
                                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              AI Sales Agent (LLM-powered)                       │
│  Reply composition + sales-agent tone + conversational memory   │
│  for buyers. Help-desk Q&A for merchants outside @commands.     │
│  Receives NLU extractor output — does NOT redo classification.  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   Admin Web Dashboard                            │
│  (separate web app, not WhatsApp)                                │
│  Merchant suspend/ban │ Listing moderation                      │
│  Buyer suspend/ban │ System monitoring │ Analytics              │
│  Conversation viewer │ Manual overrides                          │
│  Access: authenticated via email/password + 2FA                  │
└────────────────┬───────────────┬────────────────┬───────────────┘
                 │               │                │
                 ▼               ▼                ▼
          ┌──────────┐  ┌──────────────┐  ┌──────────────┐
          │ Postgres │  │ Qdrant       │  │ Object       │
          │ (read +  │  │ (delete      │  │ storage      │
          │  write)  │  │  on ban)     │  │ (listings,   │
          │          │  │              │  │  download)   │
          └──────────┘  └──────────────┘  └──────────────┘
```

## Directory Structure

```
whatAppseller/
├── docker/
│   ├── Dockerfile.webhook
│   ├── Dockerfile.worker
│   ├── Dockerfile.llm-agent
│   ├── Dockerfile.admin
│   ├── docker-compose.yml
│   └── .env.example
├── src/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # Central config (env vars, constants)
│   │   ├── dependencies.py        # FastAPI DI (db session, redis, qdrant)
│   │   └── exceptions.py          # Custom exception hierarchy
│   │
│   ├── admin/                     # Admin web dashboard (Phase 3)
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI app for admin dashboard
│   │   ├── routes/
│   │   │   ├── merchants.py       # Merchant suspension, banning (no approval gate)
│   │   │   ├── listings.py        # Listing moderation viewer
│   │   │   ├── analytics.py       # System stats, cost tracking
│   │   │   └── users.py           # Admin user mgmt, roles
│   │   ├── auth.py                # Email/password + 2FA
│   │   ├── templates/             # Jinja2 admin panel templates
│   │   └── static/                # CSS, JS assets
│   │
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models.py              # SQLAlchemy ORM models (8+ tables)
│   │   ├── schemas.py             # Pydantic request/response schemas
│   │   ├── enums.py               # Status enums, message types, roles
│   │   └── commands.py            # Merchant command definitions
│   │
│   ├── gateway/                   # Webhook gateway service
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI app instance
│   │   ├── webhook.py             # POST /webhook/whatsapp endpoint
│   │   ├── signature.py           # X-Hub-Signature-256 verification
│   │   └── dedupe.py              # Message ID deduplication (Redis)
│   │
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── queue.py               # Queue client abstraction layer
│   │   ├── router.py              # **Precedence router**:
│   │   │                          #   [1] merchant @command → merchant_commands
│   │   │                          #   [2] buyer text/image → nlu_router
│   │   │                          #   [3] free-text → LLM agent
│   │   ├── vision_pipeline.py     # Download→crop→embed→index
│   │   ├── nlu_router.py          # Cheap, high-frequency structured extraction
│   │   ├── search_pipeline.py     # Qdrant ANN → reranker → format reply
│   │   ├── notification.py        # Interest events, 24h window, outbound
│   │   ├── moderation.py          # NSFW check, merchant approval
│   │   └── merchant_commands.py   # @register, @post, @edit, etc.
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── whatsapp.py            # WhatsApp API client (send msg, media dl)
│   │   ├── object_storage.py      # S3-compatible storage operations
│   │   ├── embedding.py           # SigLIP + DINOv2 model wrappers
│   │   ├── detector.py            # Florence-2 / YOLOv11 crop
│   │   ├── qdrant_service.py      # Qdrant CRUD + ANN search
│   │   ├── postgres_service.py    # DB session management, queries
│   │   ├── redis_service.py       # Session state read/write
│   │   └── reranker.py            # Hybrid ranking formula
│   │
│   ├── llm_agent/                 # AI Sales Agent (Phase 3)
│   │   ├── __init__.py
│   │   ├── agent.py               # Main agent loop (reply composition)
│   │   ├── prompts.py             # System prompts, role definitions
│   │   ├── context_builder.py     # Builds context from NLU output + session + DB
│   │   └── tools.py               # Agent tools (search, interest, help)
│   │
│   └── shared/
│       ├── __init__.py
│       ├── correlation.py         # Correlation ID middleware
│       ├── logging.py             # Structured logging config
│       ├── rate_limiter.py        # Per-phone/per-IP rate limiting
│       ├── templates.py           # WhatsApp message templates
│       └── compliance.py          # Uganda DPA (2019) data-handling helpers
│
├── tests/
│   ├── test_webhook.py
│   ├── test_signature.py
│   ├── test_dedupe.py
│   ├── test_rate_limiter.py
│   ├── test_merchant_commands.py
│   ├── test_search_pipeline.py
│   ├── test_nlu.py
│   ├── test_reranker.py
│   ├── test_vision_pipeline.py
│   ├── test_embedding.py
│   ├── test_moderation.py
│   ├── test_postgres_service.py
│   ├── test_redis_service.py
│   ├── test_llm_agent.py
│   ├── test_compliance.py
│   ├── test_admin_auth.py
│   ├── test_admin_merchants.py
│   ├── test_admin_listings.py
│   └── test_admin_analytics.py
│
├── migrations/                    # Alembic migrations
│   ├── env.py
│   └── versions/
│
├── requirements.txt
├── pyproject.toml
├── Makefile
└── README.md
```

## Build Roadmap (Execution Order)

### Phase 1 — Foundations

| Step | Task | Key Files |
|------|------|-----------|
| 1.1 | Project scaffolding: pyproject.toml, requirements.txt, Docker setup | pyproject.toml, docker-compose.yml, Dockerfiles |
| 1.2 | Core config + domain models + enums + schemas | `src/core/config.py`, `src/domain/` |
| 1.3 | PostgreSQL schema + Alembic migrations | `migrations/`, `src/domain/models.py` |
| 1.4 | Redis session service | `src/services/redis_service.py` |
| 1.5 | Webhook gateway: FastAPI app, signature verify, dedupe, enqueue, 200 | `src/gateway/` |
| 1.6 | **Rate limiting** (per-phone, per-IP) on webhook | `src/shared/rate_limiter.py`, `src/gateway/webhook.py` |
| 1.7 | Queue abstraction layer + **precedence router** | `src/workers/queue.py`, `src/workers/router.py` |
| 1.8 | Merchant `@register` wizard (multi-step, fully automated via WhatsApp session: business name → category → location → confirm → active immediately. No manual approval. Default status is `approved` set by automation.) | `src/workers/merchant_commands.py`, `src/services/postgres_service.py` |
| 1.9 | `@post` command (image upload → object storage, no AI; store + list) | `src/workers/merchant_commands.py`, `src/services/object_storage.py` |
| 1.10 | **@register hardening** — basic phone-number sanity checks (format, country code), per-number rate limit on registration attempts to blunt bulk fake signups | `src/workers/merchant_commands.py`, `src/shared/rate_limiter.py` |
| 1.11 | WhatsApp client (send/receive messages, media download) | `src/services/whatsapp.py` |
| 1.12 | **New-merchant soft window** — merchants in their first N days or N listings have tighter per-listing rate limits; listings go live immediately but are monitored more aggressively (optional Phase 1 toggle) | `src/workers/merchant_commands.py`, `src/core/config.py` |
| 1.13 | Correlation ID + structured logging | `src/shared/correlation.py`, `src/shared/logging.py` |

### Phase 2 — AI Pipeline

| Step | Task | Key Files |
|------|------|-----------|
| 2.1 | Object crop/detection (Florence-2 or YOLOv11) | `src/services/detector.py` |
| 2.2 | SigLIP embedding generation + Qdrant collection setup | `src/services/embedding.py`, `src/services/qdrant_service.py` |
| 2.3 | Index merchant images on `@post` (crop → embed → store in Qdrant). **A minimal moderation stub is active before any indexing occurs**: basic format/header checks (corrupt file, unsupported type, file-size sanity). This stub gets upgraded to the full NSFW model in Phase 3.3. **Phase 2 runs in a non-public/test environment until 3.3 ships.** | `src/workers/vision_pipeline.py`, `src/workers/moderation.py` |
| 2.4 | Buyer image search (embed → Qdrant ANN → raw results) | `src/workers/search_pipeline.py` |
| 2.5 | DINOv2 fine-grained scoring + business-rule reranker | `src/services/embedding.py`, `src/services/reranker.py` |
| 2.6 | **Buyer free-text NLU (stays permanently):** cheap structural extractor — intent classification + entity extraction + filter merge. Not a throwaway; Phase 3 agent consumes this output rather than rebuilding it. | `src/workers/nlu_router.py` |
| 2.7 | E2E search flow (image or text → search → rerank → format reply) | Integration across workers |

### Phase 3 — Production & AI Sales Agent

| Step | Task | Key Files |
|------|------|-----------|
| 3.1 | **AI Sales Agent** — reply composition + sales-agent tone + conversational memory. Sits downstream of NLU extractor output; does NOT redo classification. For merchants, handles only free-text outside `@command` grammar (help-desk style Q&A). | `src/llm_agent/` |
| 3.2 | Wire LLM agent into router as fallback path | `src/workers/router.py`, `src/workers/nlu_router.py` |
| 3.3 | **Upgrade moderation stub to full NSFW model** — replaces the format-check stub from 2.3 with real automated moderation (prohibited content / NSFW check) before indexing. | `src/workers/moderation.py` |
| 3.4 | Notification service + 24h window handling | `src/workers/notification.py`, `src/shared/templates.py` |
| 3.5 | PostGIS distance queries | `src/services/postgres_service.py` |
| 3.6 | Remaining merchant commands (`@edit`, `@stock`, `@price`, `@delete`, `@help`) | `src/workers/merchant_commands.py` |
| 3.7 | **WhatsApp cost tracking** (instrument per-conversation cost from day one) | `src/shared/logging.py`, `src/services/whatsapp.py` |
| 3.8 | **Admin web dashboard** — merchant/ buyer account overriding (suspend, ban), listing moderation viewer, system health monitoring | `src/admin/` |
| 3.9 | **Admin auth** — email/password + 2FA, role-based access (superadmin, moderator) | `src/admin/auth.py` |
| 3.10 | **Admin analytics** — conversation volume, search trends, cost tracking per-conversation, top merchants | `src/admin/routes/analytics.py` |
| 3.11 | **Uganda DPA (2019) compliance pass** — data retention, consent, GPS consent, phone number handling | `src/shared/compliance.py` |

## Key Design Decisions

1. **Router precedence rule (hard, enforced at the top of `router.py`)**: if the sender is in merchant mode AND the message matches the `@command` grammar, route directly to `merchant_commands.py`. The LLM agent NEVER processes structured merchant data entry. The LLM agent handles: buyer natural-language search/questions, and merchant free-text outside `@command` grammar (e.g. "how do I change my price?" — help-desk Q&A, not data entry).

2. **NLU extractor is permanent, not a throwaway**: Phase 2.6 builds a cheap structured extractor (Haiku, tool-use/JSON schema) for intent + entities. Phase 3.1's AI Sales Agent consumes this output for reply composition + conversational memory — it does NOT rebuild classification.

3. **Rate limiting is in Phase 1 (not Phase 3.5)**: the webhook gateway is internet-facing from the start; basic per-number/per-IP throttling lives in the gateway from Phase 1.

4. **All services containerized**: one Dockerfile per service type (webhook, worker, llm-agent, admin), orchestrated via docker-compose.

5. **Correlation ID = WhatsApp message ID**: traceable end-to-end from webhook → queue → worker → reply.

6. **Workers are single-purpose, retryable jobs**: no giant synchronous chains, granular dead-letter queues per stage.

7. **Hybrid ranking, not hard filtering**: price/location nudge scores, don't exclude near-misses.

8. **Never display raw similarity %**: use qualitative labels ("Closest match", "Similar style").

9. **Merchants use fixed grammar** (`@register`, `@post`, etc.), never NLP for structured data entry — enforced by router precedence rule.

10. **Admin is a third role with a web dashboard (not WhatsApp)**: all moderation, approval, suspension, and system monitoring happens through an authenticated admin web app — no admin commands over WhatsApp.

## Data Model — Additional Tables

Beyond the spec's 7 tables, add:

```
admins
  id, email (unique), password_hash, role (superadmin | moderator),
  is_active, last_login_at, created_at
```

The `moderation_queue.reviewed_by` column becomes a FK → `admins.id`.

The `merchants.status` field values are: `approved` (default, set by automation on @register completion), `suspended` (admin override — revokes access, hides listings), `banned` (admin revoke — removes products from Qdrant + Postgres, prevents future registration from same phone). No `pending` status; there is no manual approval gate for new merchants.

A dedicated `buyers` table is used (not overloading `conversations` — conversations is a log, not an identity store):

```
buyers
  id, phone_number (unique), is_banned, banned_reason, banned_at,
  created_at (first contact), last_active_at
```

Buyer accounts are implicitly created on first inbound message. Admin can suspend/ban via dashboard, which is enforced at the router level before any NLU or search processing.

## Three-Role System

| Role | Interface | Capabilities |
|------|-----------|--------------|
| **Buyer** | WhatsApp (via AI Sales Agent) | Send photos/text for search, browse ranked results, tap "Interested", receive merchant responses |
| **Merchant** | WhatsApp (via `@commands` + optional AI Sales Agent for help) | `@register` (multi-step wizard via WhatsApp, fully automated → active immediately), `@post`, `@edit`, `@stock`, `@price`, `@delete`, `@help`. Outside commands: ask AI Agent help-desk questions |
| **Admin** | Web dashboard (separate FastAPI app) | Override merchant/buyer accounts (suspend/ban via dashboard), moderate listings, view analytics/system health, conversation logs, cost tracking, admin user management. No manual approval for registration — admin can revoke or suspend at any time. |
