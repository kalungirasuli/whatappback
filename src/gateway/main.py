from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from redis.asyncio import Redis

from src.core.config import settings
from src.core.dependencies import init_redis, close_redis, get_redis, init_storage
from src.gateway.webhook import router as webhook_router
from src.shared.logging import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    await init_storage()
    yield
    await close_redis()


app = FastAPI(title="whatAppseller Webhook Gateway", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
