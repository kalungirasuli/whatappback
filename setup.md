# whatAppseller — Development Setup Guide

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.14+ | Backend runtime |
| Docker Desktop | Latest | Postgres, Redis, Qdrant, MinIO |
| NVIDIA GPU | GTX 1660+ (6GB VRAM) | Model inference |
| CUDA Toolkit | 12.1+ | GPU acceleration |
| Ollama | Latest | Gemma2 NLU inference |

---

## Step 1: Python Dependencies

```bash
# Core API dependencies
pip install -r requirements.txt

# AI/ML dependencies (Phase 2)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install ultralytics sentence-transformers
```

### What Gets Installed

| Package | Purpose | Auto-Downloads |
|---------|---------|----------------|
| `torch` + `torchvision` | GPU-accelerated ML | CUDA runtime |
| `ultralytics` | YOLOv11 object detection | `yolo11n.pt` (~6 MB) on first use |
| `sentence-transformers` | SigLIP + DINOv2 embeddings | Models from HuggingFace (~800 MB total) on first use |

---

## Step 2: Ollama Setup

### Install Ollama

Download from https://ollama.com and install.

### Add to PATH (optional)

```powershell
# Ollama installs to:
C:\Users\CONRAD\AppData\Local\Programs\Ollama\ollama.exe

# Or add to PATH via System Environment Variables
```

### Pull Gemma2 Model

```powershell
& "C:\Users\CONRAD\AppData\Local\Programs\Ollama\ollama.exe" pull gemma2:2b
```

| Model | Size | VRAM Usage | Quality |
|-------|------|------------|---------|
| `gemma2:2b` | ~1.6 GB | ~2 GB | Good for NLU tasks |
| `gemma2:9b` | ~5.5 GB | ~6 GB | Better but tight on 6GB VRAM |

### Verify Ollama is Running

```powershell
& "C:\Users\CONRAD\AppData\Local\Programs\Ollama\ollama.exe" list
```

---

## Step 3: Environment Variables

Create `.env` file in project root:

```env
# WhatsApp
WHATSAPP_ACCESS_TOKEN=your_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_id
WHATSAPP_APP_SECRET=your_secret
WHATSAPP_WEBHOOK_VERIFY_TOKEN=your_verify_token

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/whatappseller

# Redis
REDIS_URL=redis://localhost:6380/0

# Object Storage (MinIO)
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin

# Qdrant
QDRANT_URL=http://localhost:6333

# Ollama (for Gemma2 NLU)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma2:2b

# JWT
JWT_SECRET=change-me-in-production
ADMIN_JWT_SECRET=change-me-in-production

# SigLIP Model (default is correct)
SIGLIP_MODEL=google/siglip-base-patch16-224
DINOV2_MODEL=facebook/dinov2-base
```

---

## Step 4: Docker Services

```bash
cd docker
docker compose up -d
```

### Services & Ports

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL (PostGIS) | 5433 | Primary database |
| Redis | 6380 | Session state, caching |
| Qdrant | 6333/6334 | Vector similarity search |
| MinIO | 9000/9001 | Object storage (images) |
| Webhook Gateway | 8000 | WhatsApp webhook |
| Worker | — | Background message processing |
| Admin Dashboard | 8001 | Admin panel |
| REST API | 8002 | Frontend API |

---

## Step 5: Database Migrations

```bash
alembic upgrade head
```

This runs migrations:
- `0001` — 9 core tables (merchants, products, buyers, conversations, etc.)
- `0002` — subscription tables + seed plans
- `0003` — unified users table

---

## Step 6: Run Services

### Development (all in one terminal)
```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8002 --reload
```

### With Docker
```bash
cd docker
docker compose up -d
```

---

## Models Auto-Download Summary

No manual model downloads needed. Models download on first use:

| Model | Source | Size | Trigger |
|-------|--------|------|---------|
| `yolo11n.pt` | ultralytics | ~6 MB | First image detection |
| `google/siglip-base-patch16-224` | HuggingFace | ~350 MB | First embedding call |
| `facebook/dinov2-base` | HuggingFace | ~450 MB | First DINOv2 embedding |
| `gemma2:2b` | Ollama registry | ~1.6 GB | `ollama pull` (manual) |

**Total model download: ~2.4 GB**

---

## GPU Requirements

| Task | VRAM Used | Speed (GTX 1660 Super) |
|------|-----------|------------------------|
| YOLOv11 detection | ~0.5 GB | ~0.3s per image |
| SigLIP embedding | ~1 GB | ~0.2s per image |
| DINOv2 embedding | ~1.5 GB | ~0.3s per image |
| Gemma2:2b NLU | ~2 GB | ~1-3s per query |

**Total peak VRAM: ~5 GB** (fits in 6GB)

---

## Verify Installation

```python
# Test GPU
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# Test YOLO
python -c "from ultralytics import YOLO; model = YOLO('yolo11n.pt'); print('YOLO OK')"

# Test Sentence Transformers
python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('google/siglip-base-patch16-224'); print('SigLIP OK')"

# Test Ollama
python -c "import httpx; r = httpx.get('http://localhost:11434/api/tags'); print(f'Ollama models: {[m[\"name\"] for m in r.json().get(\"models\", [])]}')"
```

---

## Troubleshooting

### "CUDA out of memory"
- Close other GPU apps (Chrome, Discord)
- Use `gemma2:2b` instead of `gemma2:9b`

### "ultralytics not installed"
- Run: `pip install ultralytics`

### "sentence-transformers not installed"
- Run: `pip install sentence-transformers`

### Ollama not responding
- Start Ollama app or run: `ollama serve`
- Verify: `ollama list`

### Qdrant connection refused
- Start Docker: `cd docker && docker compose up -d qdrant`
- Check: `curl http://localhost:6333/healthz`
en