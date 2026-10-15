import logging
from datetime import datetime, timezone

from redis.exceptions import RedisError

from app.core.config import settings
from app.redis.connection import redis_client

logger = logging.getLogger(__name__)
_PROVIDERS = ("groq", "gemini", "mistral")
_FEATURES = (
    "chat_stream",
    "completion",
    "embedding",
    "moderation",
    "product_content",
    "product_description",
    "product_search_agent",
)
_USAGE_TTL_SECONDS = 48 * 60 * 60


class AIProviderQuotaExceeded(ValueError):
    """Raised when a configured daily provider request limit has been reached."""


class AIUsageUnavailable(ValueError):
    """Raised when quota enforcement cannot be checked safely."""


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def record_ai_provider_request(provider: str, feature: str) -> int | None:
    day = _utc_day()
    provider_key = f"ai:usage:{day}:{provider.casefold()}"
    feature_key = f"{provider_key}:{feature}"
    quotas = {name.casefold(): limit for name, limit in settings.AI_PROVIDER_DAILY_QUOTAS.items()}
    quota = quotas.get(provider.casefold())
    try:
        usage = int(redis_client.incr(provider_key))
        if usage == 1:
            redis_client.expire(provider_key, _USAGE_TTL_SECONDS)
        if quota is not None and usage > quota:
            redis_client.decr(provider_key)
            raise AIProviderQuotaExceeded(
                f"The configured daily request limit for {provider} has been reached."
            )
        feature_usage = int(redis_client.incr(feature_key))
        if feature_usage == 1:
            redis_client.expire(feature_key, _USAGE_TTL_SECONDS)
        return usage
    except AIProviderQuotaExceeded:
        raise
    except RedisError as error:
        if quota is not None:
            raise AIUsageUnavailable(
                "AI quota tracking is unavailable; provider requests are paused until Redis recovers."
            ) from error
        logger.warning("AI usage tracking failed for %s: %s", provider, type(error).__name__)
        return None


def get_ai_usage_summary() -> dict[str, object]:
    day = _utc_day()
    configured_quotas = {
        name.casefold(): limit for name, limit in settings.AI_PROVIDER_DAILY_QUOTAS.items()
    }
    provider_usage: list[dict[str, object]] = []
    try:
        for provider in _PROVIDERS:
            raw_usage = redis_client.get(f"ai:usage:{day}:{provider}")
            usage = int(raw_usage) if raw_usage is not None else 0
            feature_usage = {}
            for feature in _FEATURES:
                raw_feature_usage = redis_client.get(
                    f"ai:usage:{day}:{provider}:{feature}"
                )
                feature_usage[feature] = (
                    int(raw_feature_usage) if raw_feature_usage is not None else 0
                )
            provider_usage.append({
                "provider": provider,
                "requests": usage,
                "daily_limit": configured_quotas.get(provider),
                "feature_requests": feature_usage,
            })
    except (RedisError, TypeError, ValueError) as error:
        logger.exception("Unable to read AI usage counters")
        raise AIUsageUnavailable("AI usage monitoring is temporarily unavailable.") from error
    return {"date_utc": day, "providers": provider_usage}
