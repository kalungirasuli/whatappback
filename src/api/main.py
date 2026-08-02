from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.dependencies import init_redis, close_redis, init_storage
from src.shared.logging import setup_logging
from src.shared.reqlog import log_frontend_request
from src.auth.main import router as auth_router
from src.api.routes.products import router as products_router
from src.api.routes.search import router as search_router
from src.api.routes.clients import router as clients_router
from src.api.routes.merchants import router as merchants_router
from src.api.routes.nlu import router as nlu_router
from src.api.routes.chat import router as chat_router
from src.api.routes.result_codes import router as result_codes_router

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    await init_storage()
    yield
    await close_redis()


app = FastAPI(title="whatAppseller API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_all_frontend_requests(request, call_next):
    """Trace every request crossing the boundary (method, path, payload metadata,
    response status and latency) so frontend vs backend data can be compared."""
    import time

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    query = request.url.query
    log_frontend_request(
        method=request.method,
        path=request.url.path,
        query=f"?{query}" if query else "",
        client=request.client.host if request.client else "-",
        content_type=request.headers.get("content-type", "") or "-",
        content_length=request.headers.get("content-length", "") or "-",
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response

app.include_router(auth_router)
app.include_router(products_router)
app.include_router(search_router)
app.include_router(clients_router)
app.include_router(merchants_router)
app.include_router(nlu_router)
app.include_router(chat_router)
app.include_router(result_codes_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api"}
