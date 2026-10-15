import json
import logging
from collections.abc import AsyncIterator
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_optional_chat_user
from app.celery.tasks import generate_product_content_task
from app.celery.worker import require_celery_worker
from app.core.rate_limit import ai_rate_limit_key, limiter
from app.database.database import get_db
from app.models.background_job import BackgroundJob
from app.models.user import User
from app.services.ai_chat_service import (
    CatalogSearchResult,
    ProviderInterruptedError,
    ProvidersUnavailableError,
    configured_providers,
    fallback_catalog_reply,
    greeting_response,
    retrieve_catalog_context,
    stream_chat_response,
)
from app.services.ai_features_service import (
    AIServiceUnavailableError,
    generate_product_content,
    generate_product_description,
    get_cached_value,
    response_cache_key,
    run_product_search_agent,
    set_cached_value,
)
from app.services.ai_governance import AIUsageUnavailable, get_ai_usage_summary
from app.utils.response import success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Shopping Assistant"])


@router.get("/admin/usage")
def ai_usage_dashboard(
    _current_user: User = Depends(get_current_admin),
) -> dict[str, object]:
    try:
        usage = get_ai_usage_summary()
    except AIUsageUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return success_response(data=usage, message="AI provider usage fetched successfully")


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=3000)


class AIChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1500)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


class ProductDescriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    price: float = Field(ge=0, allow_inf_nan=False)
    details: str | None = Field(default=None, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProductContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    price: float = Field(ge=0, allow_inf_nan=False)
    stock: int = Field(default=0, ge=0)
    brand: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    features: str | None = Field(default=None, max_length=4000)
    existing_description: str | None = Field(default=None, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProductAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1500)


def _sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"


@router.post("/chat/stream")
@limiter.limit("8/minute", key_func=ai_rate_limit_key)
def stream_ai_chat(
    request: Request,
    chat_request: AIChatRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_chat_user),
) -> StreamingResponse:
    question = chat_request.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Message must not be blank.")

    greeting = greeting_response(question)
    search_result = (
        CatalogSearchResult(context="", sources=[], reply=greeting)
        if greeting is not None
        else retrieve_catalog_context(
            db,
            question,
            [(turn.role, turn.content) for turn in chat_request.history],
        )
    )
    providers = configured_providers() if search_result.reply is None else []

    history = [(turn.role, turn.content) for turn in chat_request.history]
    cache_key = response_cache_key(
        "chat",
        {
            "scope": f"user:{current_user.id}" if current_user is not None else ai_rate_limit_key(request),
            "question": question,
            "context": search_result.context,
            "history": history,
            "providers": [(provider.name, provider.model) for provider in providers],
            "prompt": "shopping-assistant-v3",
        },
    )

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
        if not providers:
            yield _sse({"type": "token", "text": fallback_catalog_reply(search_result)})
            yield _sse({"type": "done"})
            return
        cached_response = get_cached_value(cache_key)
        if isinstance(cached_response, str) and cached_response:
            for offset in range(0, len(cached_response), 128):
                yield _sse({"type": "token", "text": cached_response[offset : offset + 128]})
            yield _sse({"type": "done"})
            return
        try:
            full_response: list[str] = []
            async for text in stream_chat_response(question, search_result.context, history, providers):
                full_response.append(text)
                yield _sse({"type": "token", "text": text})
            if full_response:
                set_cached_value(cache_key, "".join(full_response))
            yield _sse({"type": "done"})
        except ProvidersUnavailableError:
            logger.warning("Every configured AI provider failed for a chat request")
            if not full_response:
                yield _sse({"type": "token", "text": fallback_catalog_reply(search_result)})
                yield _sse({"type": "done"})
            else:
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


@router.post("/products/generate-description")
@limiter.limit("5/minute", key_func=ai_rate_limit_key)
def generate_description(
    request: Request,
    response: Response,
    generation_request: ProductDescriptionRequest,
    _current_user: User = Depends(get_current_admin),
):
    try:
        description = generate_product_description(
            generation_request.name,
            generation_request.price,
            generation_request.details,
            cache_scope=ai_rate_limit_key(request),
        )
    except AIServiceUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return success_response(
        data={"description": description},
        message="Product description generated successfully",
    )


@router.post("/products/generate-content")
@limiter.limit("5/minute", key_func=ai_rate_limit_key)
def generate_product_draft(
    request: Request,
    response: Response,
    generation_request: ProductContentRequest,
    _current_user: User = Depends(get_current_admin),
):
    try:
        content = generate_product_content(
            generation_request.name,
            generation_request.price,
            brand=generation_request.brand,
            category=generation_request.category,
            feature_details=generation_request.features,
            stock=generation_request.stock,
            existing_description=generation_request.existing_description,
            cache_scope=ai_rate_limit_key(request),
        )
    except AIServiceUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return success_response(
        data=content,
        message="Product description and features generated successfully",
    )


@router.post("/products/generate-content/jobs")
@limiter.limit("5/minute", key_func=ai_rate_limit_key)
def queue_product_content_generation(
    request: Request,
    response: Response,
    generation_request: ProductContentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    require_celery_worker()
    job_id = str(uuid4())
    job = BackgroundJob(
        id=job_id,
        user_id=current_user.id,
        task_type="ai_product_content",
    )
    db.add(job)
    db.commit()
    try:
        generate_product_content_task.apply_async(
            args=[job_id, current_user.id, generation_request.model_dump()],
            task_id=job_id,
        )
    except Exception as error:
        db.delete(job)
        db.commit()
        logger.exception("Unable to queue AI product content generation")
        raise HTTPException(
            status_code=503,
            detail="AI product content generation is currently unavailable.",
        ) from error
    return success_response(
        data={
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
        },
        message="AI product content generation queued",
    )


@router.post("/agent")
@limiter.limit("8/minute", key_func=ai_rate_limit_key)
def product_search_agent(
    request: Request,
    response: Response,
    agent_request: ProductAgentRequest,
    db: Session = Depends(get_db),
    _current_user: User | None = Depends(get_optional_chat_user),
):
    question = agent_request.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Message must not be blank.")
    try:
        reply, search_result = run_product_search_agent(db, question)
    except AIServiceUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    return {
        "reply": reply,
        "sources": search_result.sources,
        "label": search_result.source_label,
    }
