# Implementation Steps — whatAppseller

## Phase 1 — Foundations

| Step | Task | Status |
|------|------|--------|
| 1.1 | Project scaffolding — pyproject.toml, Docker setup | ✅ |
| 1.2 | Core config, domain models, enums, schemas | ✅ |
| 1.3 | PostgreSQL schema + Alembic migration | ✅ |
| 1.4 | Redis session service | ✅ |
| 1.5 | Webhook gateway — signature verify, dedupe, enqueue, 200 | ✅ |
| 1.6 | Rate limiting (per-phone, per-IP) | ✅ |
| 1.7 | Queue abstraction + precedence router | ✅ |
| 1.8 | Merchant `@register` wizard | ✅ |
| 1.9 | `@post` command + object storage | ✅ |
| 1.10 | `@register` hardening — phone sanity, rate limit | ✅ |
| 1.11 | WhatsApp client (full) | ✅ |
| 1.12 | New-merchant soft window | ✅ |
| 1.13 | Correlation ID + structured logging | ✅ |

## Phase 2 — AI Pipeline

| Step | Task | Status |
|------|------|--------|
| 2.1 | Object crop/detection (YOLOv11 + Pillow fallback) | ✅ |
| 2.2 | SigLIP embedding + Qdrant collection setup | ✅ |
| 2.3 | Index merchant images + moderation stub | ✅ |
| 2.4 | Buyer image search (embed → Qdrant ANN) | ✅ |
| 2.5 | DINOv2 reranker + business-rule scoring | ✅ |
| 2.6 | Buyer free-text NLU (structured extractor) | ✅ |
| 2.7 | E2E search flow integration | ✅ |

## Phase 3 — Production & AI Sales Agent

| Step | Task | Status |
|------|------|--------|
| 3.1 | AI Sales Agent (reply composition, tone, memory) | ✅ |
| 3.2 | Wire LLM agent into router | ✅ |
| 3.3 | Upgrade moderation to full NSFW model | ⏳ (stub active, full model deferred to deployment) |
| 3.4 | Notification service + 24h window | ✅ |
| 3.5 | PostGIS distance queries | ✅ |
| 3.6 | Remaining merchant commands (@edit, @stock, @price, @delete, @help) | ✅ |
| 3.7 | WhatsApp cost tracking | ✅ |
| 3.8 | Admin web dashboard (suspend/ban merchants, buyers, listings) | ✅ |
| 3.9 | Admin auth (email/password + JWT) | ✅ |
| 3.10 | Admin analytics | ✅ |
| 3.11 | Uganda DPA compliance pass | ✅ |

## Test Summary

- **Total tests: 513** (all passing)
- Phase 1: 182 tests (11 test files)
- Phase 2: 169 tests (8 test files)
- Phase 3: 162 tests (5 test files)

## Known Remaining Work

- **Step 3.3**: Full NSFW model (requires GPU + model download, deferred to deployment environment)
- **Docker verification**: PostGIS + MinIO images need to be pulled when bandwidth allows
- **Integration testing**: End-to-end test with real WhatsApp sandbox
