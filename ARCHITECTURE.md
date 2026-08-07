# whatAppSeller — Full System Architecture

## YOLO Version
**YOLOv11 Nano** (`yolo11n.pt` — Ultralytics v11, smallest model, COCO-pretrained, ~5.4MB)

---

## Infrastructure Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (whatApp/)                            │
│  React + Vite + Tailwind                                                  │
│  AuthGate → App → ChatWindow → [MessageInput, MessageBubble,            │
│  ProductSection, Sidebar, ShopManager, ProfileModal, HistoryModal]       │
│  api.ts → localStorage + Bearer token → http://localhost:8002           │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │ HTTP (multipart/form-data)
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        API GATEWAY (port 8002)                           │
│  src/api/main.py — FastAPI app                                           │
│  Middleware: CORS, reqlog (every request logged)                         │
│                                                                          │
│  Routes:                                                                 │
│  ├── /api/auth/*       OTP login/verify/refresh/me                      │
│  ├── /api/chat          POST — unified chat (Lisa + search)             │
│  │                       GET /conversations — list conversations         │
│  │                       GET /conversations/messages — restore history   │
│  ├── /api/products/*    Merchant CRUD + image upload                    │
│  ├── /api/search/*      Image/text/hybrid search (legacy endpoint)      │
│  ├── /api/clients/*     History, interests                               │
│  ├── /api/merchants/*   Merchant profile                                 │
│  └── /api/result-codes/* Code lookup                                     │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   PostgreSQL │  │    Redis     │  │    Qdrant    │
│   (port 5433)│  │  (port 6380) │  │  (port 6333) │
│              │  │              │  │              │
│ Tables:      │  │ Keys:        │  │ Collection:  │
│ users        │  │ otp:{phone}  │  │ products     │
│ merchants    │  │ otp_rate:*   │  │   siglip=768 │
│ products     │  │ refresh:{id} │  │   dinov2=768 │
│ product_imgs │  │ session:*    │  │   text=768   │
│ chat_inter.  │  │ lisa:hist:{n}│  │              │
│ buyers       │  │ rate:*       │  │              │
│ result_codes │  │              │  │              │
│ admins       │  │              │  │              │
└──────────────┘  └──────────────┘  └──────────────┘

┌──────────────┐  ┌──────────────────────┐
│    MinIO     │  │       Ollama         │
│  (port 9000) │  │    (port 11434)      │
│              │  │                      │
│ Bucket:      │  │ Model: gemma2:2b     │
│ whatapp-     │  │                      │
│ seller-      │  │ Used by: LisaAgent   │
│ images       │  │ - decide()           │
│              │  │ - present_results()  │
│              │  │ - compose_opening()  │
└──────────────┘  └──────────────────────┘
```

---

## POST /api/chat — Full Pipeline (top to bottom)

### 1. AUTH
```
get_current_user (JWT Bearer token → user_id, phone)
```

### 2. PARSE
```
Extract: text, files → image_bytes_list, buyer_location
Validate: max 10MB per file
```

### 3. RECALL CHECK
```
If text matches "RS-XXXX" format → lookup result_code → return cached results
If text matches "last / previous / saved search" → return cached results
```

### 4. IMAGE DESCRIPTION
```
_describe_image(image_bytes)
├── ObjectDetector.detect_and_crop(bytes)
│   ├── YOLOv11n (yolo11n.pt) → detect objects
│   ├── Sort by confidence × area (descending)
│   ├── Filter low-confidence (< 0.50)
│   ├── If NO objects → center_crop fallback (center 80% of image)
│   └── Return: list[CroppedObject]
│       { image_bytes, bbox, confidence, label }
│
├── Filter NOISY_LABELS (person, full_image, etc)
├── If best_conf < 0.60 → "Products matching your image" (don't trust YOLO)
└── → "I see a car, a phone in your image"
```

### 5. LISA DECIDES
```
LisaAgent.decide(redis, user_id, text, has_image, image_note)
├── Clear Redis history if image-only (no text) — prevents context leak
├── Load history from Redis: lisa:history:{user_id}
├── Build prompt with last 6 turns
├── Call Ollama /api/chat → gemma2:2b
├── Parse JSON → { action: "chat"|"search", reply, search_text }
└── Photo ALWAYS forces search (override: turn.action != "search" and has_images → search anyway)
```

### 6. BUILD SEARCH INTENTS
```
For each image → visual_search intent
If has_text → product_search intent
Each intent has: type, description, entities
```

### 7. EXECUTE INTENT SEARCHES
```
execute_intent_searches(intents, images_bytes, location)

For visual_search:
├── SearchPipeline.search_by_image(image_bytes)
│   │
│   ├── A. ObjectDetector.detect_and_crop(bytes)
│   │      → crops[] sorted by conf×area (primary first)
│   │      → primary = crops[0].image_bytes
│   │      → labels = [c.label for c in crops]
│   │
│   ├── B. EmbeddingService
│   │      ├── embed_image(primary) → SigLIP (768d)
│   │      │   Model: google/siglip-base-patch16-224
│   │      │   Pipeline: bytes → PIL → exif_transpose → RGB → encode → normalize
│   │      └── embed_image_dinov2(primary) → DINOv2 (768d)
│   │          Model: facebook/dinov2-base
│   │          Pipeline: same as SigLIP
│   │
│   ├── C. QdrantService.hybrid_search(siglip, dinov2, 50)
│   │      ├── search_similar(siglip, 50, "siglip") → siglip_results
│   │      ├── search_similar(dinov2, 50, "dinov2") → dinov2_results
│   │      ├── Combine: 0.6 × siglip_score + 0.4 × dinov2_score
│   │      └── Sort descending, return top 50
│   │
│   ├── D. Reranker.rerank(hybrid_results, location, price_range)
│   │      ├── Base weight: 0.6 × hybrid_score
│   │      ├── Text boost: +0.1 if query text matches product name
│   │      ├── Price proximity: +0.1 if in buyer's range
│   │      ├── Location boost: +0.1 if seller < 10km away
│   │      ├── Sort → assign rank number
│   │      ├── match_label: "Closest match" / "Similar style" / "Good alternative"
│   │      └── Return list[RerankedResult]
│   │
│   └── E. apply_consistency_filter(reranked, preferred_family)
│          ├── Determine family from YOLO labels:
│          │   family_for_detector_labels(labels)
│          │   "car" → vehicles, "cell phone" → electronics
│          │   Check: best_conf < 0.60 → skip detector family (don't trust weak YOLO)
│          ├── If no detector family → use top result's category family
│          ├── Filter: keep only same-family results
│          ├── If filter empties list → fallback to top result's family (recovers from wrong YOLO)
│          ├── Score band: keep results ≥ top_score × 0.35
│          └── Recompute rank + match_label

For product_search (text):
├── search_by_text(text)
│   ├── embed_text(text) → SentenceTransformer(all-mpnet-base-v2) (768d)
│   ├── qdrant.search_similar(text_vec, "text") → top 50
│   ├── reranker.rerank(results, query_text=text)
│   └── apply_consistency_filter(reranked)
```

### 8. BUILD SECTIONS
```
For each intent's results:
├── _load_products(product_ids, db) → full product data from PostgreSQL
├── _format_results(reranked, db_products) → JSON with images, prices, merchants
├── Add distance_km (Haversine) if buyer location provided
├── Section label: starts with intent.description
└── Override label to "Matching {category}" if top result has category
```

### 9. LISA PRESENTS + OPENING
```
compose_opening(image_note, caption)
├── Ollama → "Nice car! Let me find similar vehicles."
└── Fallback: "I can see your image - searching now!"

present_results(redis, user_id, top_summary)
├── Ollama → natural WhatsApp-style summary (varied, not template-based)
└── Fallback: "Here's what I found for you!"
```

### 10. BUILD FOLLOW-UP
```
_build_follow_up(text_topic, text_family, image_family)
If text_family ≠ image_family (caption and image disagree):
→ "You also mentioned shoes — please upload a photo..."
```

### 11. GENERATE RESULT CODE
```
ResultCodeService.generate(db) → "RS-XXXX"
Store: code, user_id, search_query, image_description,
       category, product_ids, sample_products
```

### 12. BUILD REPLY
```json
{
  "reply_type": "conversation",
  "result_code": "RS-XXXX",
  "messages": [
    { "type": "text", "text": "Nice car! Let me find similar vehicles." },
    { "type": "search_results",
      "label": "Matching cars",
      "total": 4,
      "results": [
        { "product_id": 4, "name": "Car 4", "price": 30000000,
          "currency": "UGX", "category": "cars",
          "score": 0.60, "match_label": "Closest match",
          "merchant": { "business_name": "Prime Motors Kampala" },
          "images": [{ "url": "http://minio:9000/...", "is_primary": true }] }
      ]
    },
    { "type": "text", "text": "Would you like to see any specific make or year?" }
  ],
  "response_text": "...",   // backward compat
  "sections": [...]          // backward compat
}
```

### 13. LOG + RETURN
```
ChatLogService.log(db, ...) → chat_interactions table
LisaAgent.record_turn(redis, ...) → lisa:history:{user_id}
Return HTTP 200 with reply JSON
```

---

## Indexing Pipeline (product image upload)

```
POST /api/products/{id}/images (multipart file upload)
       │
       ▼
  upload_image(bytes, content_type) → MinIO (S3-compatible)
       ├── Key: products/{uuid}.jpg
       ├── Bucket: whatappseller-images
       └── Returns: storage_url (http://localhost:9000/whatappseller-images/...)
       │
       ▼
  VisionPipeline.process_product_image(
      product_id, image_bytes, merchant_id,
      product_name, category, brand, price,
      merchant_lat, merchant_lng)
       │
       ├── 1. Moderation: check_image(bytes)
       │      ├── Format/header validation (corrupt file, unsupported type, size sanity)
       │      └── Returns: { is_approved: bool, reason?: str }
       │
       ├── 2. ObjectDetector.detect_and_crop(bytes)
       │      ├── YOLOv11n → detect products in catalog image
       │      ├── Sort crops by confidence × area (descending)
       │      └── Returns crops[] (one per detected object)
       │
       ├── 3. EmbeddingService
       │      ├── embed_image(primary_crop) → SigLIP vector (768d)
       │      ├── embed_image_dinov2(primary_crop) → DINOv2 vector (768d)
       │      └── embed_text(name + brand + category) → text vector (768d)
       │
       └── 4. QdrantService.upsert_product(id, siglip, dinov2, text, metadata)
              → Point { id, vector: { siglip, dinov2, text }, payload: metadata }
              → Metadata includes: product_id, merchant_id, product_name,
                                   category, brand, price, merchant_lat/lng,
                                   crops_count
```

---

## Frontend Data Flow (react side)

```
App.tsx
├── On mount: localStorage → restore chat messages (instant)
├── Fallback: GET /api/chat/conversations/messages → restore from backend
├── handleSend(text, attachment?)
│   ├── Add user message to chat state + localStorage
│   ├── POST /api/chat (FormData: text + files)
│   ├── Parse reply.messages[]:
│   │   ├── "text" type → render as MessageBubble (text only)
│   │   └── "search_results" type → render as MessageBubble + ProductSection
│   │       ├── Partition: results[0] = ClosestMatchCard (highlighted)
│   │       └── Partition: results[1:] = ProductCard grid (Related matches)
│   └── Save full chat to localStorage after each message
│
├── ProductSection.tsx
│   ├── ClosestMatchCard (full-width, green border, large image)
│   │   └── Image → Name → Merchant → Price → Badges → "I'm interested" button
│   └── ProductCard (vertical grid, 2-col)
│       └── Image → Name → Merchant → Price → Badges → "I'm interested" button
│
├── ChatWindow.tsx
│   ├── Welcome screen (empty chat): quick-action chips
│   │   └── [Find a car] [Latest phones] [Browse shoes] [Upload a photo]
│   └── Conversation view: message bubbles + MessageInput
│
├── MessageBubble.tsx
│   ├── User: right-aligned, green bg, image preview + caption
│   ├── AI: left-aligned, white bg, text + product cards
│   └── Staggered fade-in animation (250ms, slide-up 8px)
│
└── AuthGate.tsx
    ├── Phone input → POST /api/auth/request-otp
    ├── OTP input → POST /api/auth/verify-otp
    └── Sets access_token + refresh_token in localStorage
```

---

## Key Config Values

| Setting | Value | Purpose |
|---------|-------|---------|
| YOLO model | `yolo11n.pt` | Object detection (COCO 80-class at 640px) |
| YOLO confidence min | 0.50 | Minimum detection confidence to consider |
| YOLO skip threshold | 0.60 | Don't trust YOLO family if best conf below this |
| SigLIP model | `google/siglip-base-patch16-224` | Visual embedding (768-dim) |
| DINOv2 model | `facebook/dinov2-base` | Visual embedding (768-dim) |
| Text model | `sentence-transformers/all-mpnet-base-v2` | Text embedding (768-dim) |
| Hybrid weight | 0.6 SigLIP : 0.4 DINOv2 | Score fusion for image search |
| Score band ratio | 0.35 | Keep results scoring ≥ top × 0.35 after filter |
| Ollama model | `gemma2:2b` | Lisa AI assistant |
| Ollama URL | `http://localhost:11434` | Local Ollama server |
| JWT access expiry | 4320 min (3 days) | Auth token lifetime |
| JWT refresh expiry | 30 days | Refresh token lifetime |
| OTP expiry | 300 seconds | One-time password validity |
| OTP rate limit | Disabled (dev) | Controlled via `.env`: `OTP_RATE_LIMIT_ENABLED=false` |
| Image max size | 10 MB | Per uploaded file |

---

## Category Family Mappings

### Product categories → families (src/services/categories.py)
```
cars, automotive, vehicles, motorcycles, trucks → vehicles
phone, phones, electronics, laptops, computers → electronics
shoes, footwear → shoes
clothing, apparel → clothing
furniture, home → furniture
beauty, cosmetics → beauty
food → food
accessories → accessories
groceries → groceries
```

### YOLO detector labels → families
```
car, truck, bus, motorcycle, bicycle, train, boat, airplane → vehicles
cell phone, laptop, tv, remote, keyboard, mouse → electronics
handbag, backpack, suitcase, umbrella, clock, book, bottle, cup, vase → accessories
```

---

## Directory Reference

```
whatAppseller/
├── src/
│   ├── api/
│   │   ├── main.py              FastAPI app + middleware + route registration
│   │   └── routes/
│   │       ├── chat.py           Unified chat endpoint (Lisa + search + context)
│   │       ├── products.py       Merchant product CRUD + image upload
│   │       ├── search.py         Legacy search endpoints (image/text/hybrid)
│   │       ├── clients.py        Client interests + history
│   │       ├── merchants.py      Merchant profile management
│   │       ├── nlu.py            NLU debug/testing endpoint
│   │       └── result_codes.py   Result code lookup
│   ├── auth/                     JWT + OTP authentication
│   ├── core/
│   │   ├── config.py             Central config (all settings)
│   │   └── dependencies.py       FastAPI DI (db, redis)
│   ├── domain/
│   │   ├── models.py             SQLAlchemy ORM models
│   │   ├── schemas.py            Pydantic request/response types
│   │   └── enums.py              Role enums, status enums
│   ├── services/
│   │   ├── detector.py           ObjectDetector (YOLOv11n + center crop)
│   │   ├── embedding.py          EmbeddingService (SigLIP + DINOv2 + text)
│   │   ├── qdrant_service.py     QdrantService (CRUD + hybrid_search)
│   │   ├── reranker.py           Reranker (score fusion + ranking)
│   │   ├── lisa_agent.py         LisaAgent (Ollama chat assistant)
│   │   ├── ocr.py                OcrService (rapidocr-onnxruntime, opt-in)
│   │   ├── categories.py         Category → family mapping
│   │   ├── object_storage.py     MinIO S3 upload/delete
│   │   ├── chat_log_service.py   Chat interaction persistence
│   │   └── result_code_service.py Result code generation + storage
│   ├── workers/
│   │   ├── search_pipeline.py    SearchPipeline (image + text search)
│   │   ├── vision_pipeline.py    VisionPipeline (product image → index)
│   │   ├── nlu_router.py         execute_intent_searches + intent types
│   │   └── router.py             Message routing (worker queue entry point)
│   └── shared/
│       ├── reqlog.py             Request/response logging (CHAT-IN/OUT, LISA, REQ)
│       └── ...
└── scripts/
    ├── eval_accuracy.py          Accuracy benchmark harness
    ├── reindex_products.py       Full catalog re-indexer
    ├── seed_mock_inventory.py    Seed 13 products + 3 merchants
    └── reset_db.py               Drop + recreate PostgreSQL database

whatApp/
├── src/
│   ├── App.tsx                   Main app state, chat logic, localStorage
│   ├── api.ts                    API client (fetch + auto-refresh + multipart)
│   ├── types.ts                  TypeScript types
│   ├── data.ts                   Defaults, avatars, timestamps
│   ├── index.css                 Tailwind + WhatsApp theme + animations
│   └── components/
│       ├── AuthGate.tsx           OTP login screen
│       ├── ChatWindow.tsx         Chat layout + welcome + messages
│       ├── ChatHeader.tsx         Header with avatar + menu
│       ├── Sidebar.tsx            Conversation list (not rendered currently)
│       ├── MessageBubble.tsx      Chat message (text/image/products)
│       ├── MessageInput.tsx       Text input + file picker + send button
│       ├── ProductSection.tsx     Product cards (closest match + related)
│       ├── ShopManagementModal.tsx Merchant product CRUD
│       ├── ShopRegistrationForm.tsx Merchant onboarding form
│       ├── ProfileModal.tsx       User profile editor
│       ├── HistoryModal.tsx       Interests + search history
│       └── FormField.tsx          Reusable form field
```
