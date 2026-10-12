import json
import logging
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.database.database import get_db
from app.services.ai_chat_service import (
    CatalogSearchResult,
    ProviderInterruptedError,
    ProvidersUnavailableError,
    configured_providers,
    greeting_response,
    retrieve_catalog_context,
    stream_chat_response,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Shopping Assistant"])


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=3000)


class AIChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1500)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


def _sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"


@router.post("/chat/stream")
@limiter.limit("8/minute")
def stream_ai_chat(
    request: Request,
    chat_request: AIChatRequest,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    question = chat_request.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Message must not be blank.")

    greeting = greeting_response(question)
    search_result = (
        CatalogSearchResult(context="", sources=[], reply=greeting)
        if greeting is not None
        else retrieve_catalog_context(db, question)
    )
    providers = configured_providers() if search_result.reply is None else []
    if search_result.reply is None and not providers:
        raise HTTPException(
            status_code=503,
            detail="AI chat is not configured. Add at least one AI provider API key to the backend environment.",
        )

    history = [(turn.role, turn.content) for turn in chat_request.history]

    async def event_stream() -> AsyncIterator[str]:
        yield _sse(
            {
                "type": "sources",
                "sources": search_result.sources,
                "label": search_result.source_label,
            }
        )
        if search_result.reply is not None:
            yield _sse({"type": "token", "text": search_result.reply})
            yield _sse({"type": "done"})
            return
        try:
            async for text in stream_chat_response(question, search_result.context, history, providers):
                yield _sse({"type": "token", "text": text})
            yield _sse({"type": "done"})
        except ProvidersUnavailableError:
            logger.warning("Every configured AI provider failed for a chat request")
            yield _sse(
                {
                    "type": "error",
                    "message": "The AI assistant is temporarily unavailable. Please try again shortly.",
                }
            )
        except ProviderInterruptedError:
            logger.warning("AI response stream ended before completion")
            yield _sse(
                {
                    "type": "error",
                    "message": "The response was interrupted. Please try sending your message again.",
                }
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
