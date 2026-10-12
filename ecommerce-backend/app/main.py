from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    general_exception_handler,
)
from app.core.rate_limit import limiter

from app.api.v1.auth import router as auth_router
from app.api.v1.products import router as product_router
from app.api.v1.cart import router as cart_router
from app.api.v1.orders import router as order_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.chats import router as chats_router
from app.api.v1.ai_chat import router as ai_chat_router


from app.websocket.routes import router as websocket_router

app = FastAPI(
    title="E-commerce Backend API",
    docs_url=None if settings.ENVIRONMENT.lower() == "production" else "/docs",
    redoc_url=None if settings.ENVIRONMENT.lower() == "production" else "/redoc",
    openapi_url=None if settings.ENVIRONMENT.lower() == "production" else "/openapi.json",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type"],
    expose_headers=["Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

app.mount(
    "/uploads",
    StaticFiles(directory=Path(__file__).resolve().parent / "uploads"),
    name="uploads",
)

app.add_exception_handler(
    AppException,
    app_exception_handler,
)
app.add_exception_handler(
    Exception,
    general_exception_handler,
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if not request.url.path.startswith("/uploads/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if settings.ENVIRONMENT.lower() == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

app.include_router(auth_router)
app.include_router(product_router)
app.include_router(cart_router)
app.include_router(order_router)
app.include_router(jobs_router)
app.include_router(chats_router)
app.include_router(ai_chat_router)
app.include_router(websocket_router)

@app.get("/")
def root():
    return {"message": "API is running"}