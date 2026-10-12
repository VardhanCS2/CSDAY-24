from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings
from app.core.security import decode_token


def ai_rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.casefold() == "bearer":
        payload = decode_token(token)
        subject = payload.get("sub") if payload else None
        if payload and payload.get("token_type") == "access" and str(subject).isdigit():
            return f"ai-user:{subject}"
    return f"ai-ip:{get_remote_address(request)}"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
    headers_enabled=True,
)
