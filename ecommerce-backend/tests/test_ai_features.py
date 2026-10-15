import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_admin
from app.api.v1 import ai_chat, products
from app.core.rate_limit import ai_rate_limit_key, limiter
from app.core.security import create_access_token
from app.database.database import get_db
from app.main import app
from app.services import ai_features_service as features
from app.services import product_categories
from app.services.ai_chat_service import AIProvider, CatalogSearchResult


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex):
        self.values[key] = value
        self.expirations[key] = ex

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def decr(self, key):
        self.values[key] = int(self.values.get(key, 0)) - 1
        return self.values[key]

    def expire(self, key, seconds):
        self.expirations[key] = seconds
        return True


class FakeProductQuery:
    def __init__(self, products):
        self.products = products

    def order_by(self, _column):
        return self

    def all(self):
        return self.products


class FakeProductDB:
    def __init__(self, products):
        self.products = products

    def query(self, _model):
        return FakeProductQuery(self.products)


def test_ai_response_cache_uses_configured_ttl_and_survives_redis_outages(monkeypatch):
    cache = MemoryRedis()
    monkeypatch.setattr(features, "redis_client", cache)

    features.set_cached_value("ai:test", {"answer": "cached"})

    assert features.get_cached_value("ai:test") == {"answer": "cached"}
    assert cache.expirations["ai:test"] == features.settings.AI_RESPONSE_CACHE_TTL_SECONDS

    class FailedRedis:
        def get(self, _key):
            raise features.RedisError("offline")

        def set(self, *_args, **_kwargs):
            raise features.RedisError("offline")

    monkeypatch.setattr(features, "redis_client", FailedRedis())
    assert features.get_cached_value("ai:offline") is None
    features.set_cached_value("ai:offline", {"answer": "not cached"})


def test_ai_provider_usage_enforces_daily_limits_and_reports_usage(monkeypatch):
    from app.services import ai_governance

    cache = MemoryRedis()
    monkeypatch.setattr(ai_governance, "redis_client", cache)
    monkeypatch.setattr(
        ai_governance.settings,
        "AI_PROVIDER_DAILY_QUOTAS",
        {"groq": 1},
    )

    assert ai_governance.record_ai_provider_request("groq", "chat_stream") == 1
    with pytest.raises(ai_governance.AIProviderQuotaExceeded, match="daily request limit"):
        ai_governance.record_ai_provider_request("groq", "chat_stream")

    summary = ai_governance.get_ai_usage_summary()
    groq = next(provider for provider in summary["providers"] if provider["provider"] == "groq")
    assert groq["provider"] == "groq"
    assert groq["requests"] == 1
    assert groq["daily_limit"] == 1
    assert groq["feature_requests"]["chat_stream"] == 1
    assert cache.expirations[next(key for key in cache.expirations if key.startswith("ai:usage:"))] == 48 * 60 * 60


def test_ai_usage_dashboard_is_admin_only(client, auth_headers, customer_headers, monkeypatch):
    monkeypatch.setattr(
        ai_chat,
        "get_ai_usage_summary",
        lambda: {"date_utc": "2026-10-13", "providers": []},
    )

    response = client.get("/ai/admin/usage", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["data"]["date_utc"] == "2026-10-13"
    assert client.get("/ai/admin/usage", headers=customer_headers).status_code == 403


def test_embedding_provider_fallback_orders_and_validates_vectors():
    providers = [
        features.AIEmbeddingProvider("mistral", "first-key", "mistral-embed", "https://provider.test/first"),
        features.AIEmbeddingProvider("gemini", "second-key", "gemini-embedding-001", "https://provider.test/second"),
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/first":
            return httpx.Response(503, request=request)
        requests = json.loads(request.content)["requests"]
        assert [item["content"]["parts"][0]["text"] for item in requests] == ["blue", "red"]
        assert request.headers["x-goog-api-key"] == "second-key"
        return httpx.Response(
            200,
            json={
                "embeddings": [
                    {"values": [1.0, 0.0]},
                    {"values": [0.0, 1.0]},
                ]
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        vectors = features.embed_texts(["blue", "red"], providers, client)

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    with pytest.raises(ValueError, match="duplicate vector indexes"):
        features._decode_embeddings(
            {"data": [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 0, "embedding": [0.0, 1.0]}]},
            2,
        )


def test_semantic_search_indexes_real_vectors_and_updates_changed_products(tmp_path, monkeypatch):
    monkeypatch.setattr(features.settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(features, "_semantic_client", None)
    monkeypatch.setattr(features, "_semantic_collections", {})
    monkeypatch.setattr(
        features,
        "configured_embedding_providers",
        lambda: [features.AIEmbeddingProvider("mistral", "key", "mistral-embed", "https://provider.test")],
    )

    def embed_texts(texts, _providers, task_type):
        assert task_type == "RETRIEVAL_DOCUMENT"
        return [[0.0, 1.0] if "travel mug" in text.casefold() else [1.0, 0.0] for text in texts]

    monkeypatch.setattr(features, "embed_texts", embed_texts)
    monkeypatch.setattr(features, "_embedding_for_query", lambda _query, _provider: [1.0, 0.0])
    coffee = SimpleNamespace(
        id=1, name="Coffee beans", description="A rich roasted morning brew.", price=12.0, stock=5,
    )
    mug = SimpleNamespace(
        id=2, name="Travel mug", description="Insulated cup for hot drinks.", price=18.0, stock=0,
    )
    db = FakeProductDB([coffee, mug])

    results = features.semantic_search_products(db, "morning brew", stock_available=True)

    assert [product.id for product in results] == [1]
    collection = next(iter(features._semantic_collections.values()))
    assert len(collection.get(include=["metadatas"])["ids"]) == 2

    coffee.description = "A lightweight travel mug for hot drinks."
    features.semantic_search_products(db, "morning brew")
    assert len(collection.get(include=["metadatas"])["ids"]) == 2


def test_product_categories_are_manual_standard_choices():
    assert product_categories.canonicalize_product_categories(["Mobiles", "Shoes"]) == [
        "Electronics",
        "Footwear",
    ]
    with pytest.raises(ValueError, match="no more than 3"):
        product_categories.canonicalize_product_categories(
            ["Electronics", "Footwear", "Clothing", "Furniture"]
        )
    with pytest.raises(ValueError, match="Unsupported product category"):
        product_categories.canonicalize_product_categories(["A category guessed from description"])


def test_content_moderation_fails_over_and_caches_decision(monkeypatch):
    cache = MemoryRedis()
    monkeypatch.setattr(features, "redis_client", cache)
    monkeypatch.setattr(features, "configured_providers", lambda: [
        AIProvider("groq", "test-key", "model", "https://provider.test/moderation"),
    ])

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"approved": false, "category": "unsafe", "reason": "Unsafe content"}'}}]},
            request=request,
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        features.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = features.moderate_content("A product description")

    assert result.approved is False
    assert result.category == "unsafe"
    assert features.moderate_content("A product description") == result


def test_content_moderation_uses_explicit_limited_local_fallback_without_provider(monkeypatch):
    monkeypatch.setattr(features, "configured_providers", lambda: [])
    monkeypatch.setattr(features, "redis_client", MemoryRedis())

    blocked = features.moderate_content("How to make a bomb")
    allowed = features.moderate_content("A handmade cotton shopping tote.")

    assert blocked.approved is False
    assert blocked.category == "unsafe"
    assert allowed.approved is True
    assert allowed.category == "unclassified"


def test_description_generation_uses_provider_fallback_and_rejects_moderation(monkeypatch):
    monkeypatch.setattr(features, "redis_client", MemoryRedis())
    monkeypatch.setattr(features, "configured_providers", lambda: [
        AIProvider("groq", "first-key", "model-a", "https://provider.test/first"),
        AIProvider("gemini", "second-key", "model-b", "https://provider.test/second"),
    ])
    monkeypatch.setattr(features, "moderate_content", lambda _text: features.ModerationResult(True, "safe", ""))

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/first":
            return httpx.Response(429, request=request)
        prompt = json.loads(request.content)["messages"][0]["content"]
        assert "4-6 useful sentences" in prompt
        assert "shopper vocabulary" in prompt
        assert "Never invent product attributes" in prompt
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A useful everyday product."}}]},
            request=request,
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        features.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )

    assert features.generate_product_description("Useful item", 12.0) == "A useful everyday product."

    monkeypatch.setattr(features, "moderate_content", lambda _text: features.ModerationResult(False, "unsafe", ""))
    monkeypatch.setattr(features, "get_cached_value", lambda _key: None)
    with pytest.raises(ValueError, match="did not pass content moderation"):
        features.generate_product_description("Another item", 14.0)


def test_description_generation_logs_sanitized_http_status_for_each_failed_provider(monkeypatch, caplog):
    monkeypatch.setattr(features, "redis_client", MemoryRedis())
    monkeypatch.setattr(features, "configured_providers", lambda: [
        AIProvider("mistral", "first-key", "mistral-model", "https://provider.test/first"),
        AIProvider("gemini", "second-key", "gemini-model", "https://provider.test/second"),
    ])

    def respond(request: httpx.Request) -> httpx.Response:
        status_code = 401 if request.url.path == "/first" else 429
        return httpx.Response(
            status_code,
            json={"error": {"message": "private provider response text"}},
            request=request,
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        features.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )

    with pytest.raises(features.AIServiceUnavailableError, match="All configured AI providers failed"):
        features.generate_product_description("Useful item", 12.0)

    assert "AI completion provider mistral (model mistral-model) returned HTTP 401" in caplog.text
    assert "AI completion provider gemini (model gemini-model) returned HTTP 429" in caplog.text
    assert "private provider response text" not in caplog.text


def test_structured_product_generation_only_keeps_supplied_feature_facts(monkeypatch):
    monkeypatch.setattr(features, "redis_client", MemoryRedis())
    monkeypatch.setattr(features, "configured_providers", lambda: [
        AIProvider("groq", "test-key", "model", "https://provider.test/chat"),
    ])
    generation_options = {}

    def complete(_messages, _providers, _client, **kwargs):
        generation_options.update(kwargs)
        return {
            "content": "A phone with the stated memory and storage."
        }

    monkeypatch.setattr(
        features,
        "_complete_with_fallback",
        complete,
    )

    result = features.generate_product_content(
        "Example phone",
        400,
        brand="Example",
        category="Mobile",
        feature_details="8GB RAM, 256GB storage",
    )

    assert result == {
        "description": "A phone with the stated memory and storage.",
        "features": "- 8GB RAM\n- 256GB storage",
        "generation_mode": "ai",
    }
    assert generation_options["timeout_seconds"] == 12.0


def test_product_content_generation_accepts_plain_text_from_provider(monkeypatch):
    monkeypatch.setattr(features, "redis_client", MemoryRedis())
    monkeypatch.setattr(features, "configured_providers", lambda: [
        AIProvider("groq", "test-key", "model", "https://provider.test/chat"),
    ])
    source_features = (
        "Brand: Nothing\n"
        "Display: AMOLED\n"
        "Screen Size: 6.7 inches\n"
        "RAM: 12 GB\n"
        "Storage: 256 GB\n"
        "Rear Camera: 50 MP\n"
        "Front Camera: 32 MP\n"
        "Battery: 5,000 mAh\n"
        "Charging: Fast charging\n"
        "Operating System: Android\n"
        "Connectivity: 5G, Wi-Fi, Bluetooth\n"
        "Design: Transparent-inspired design"
    )
    monkeypatch.setattr(
        features,
        "_complete_with_fallback",
        lambda *_args, **_kwargs: {
            "content": "A Nothing smartphone featuring the specifications you provided."
        },
    )

    result = features.generate_product_content(
        "Nothing Phone",
        500,
        feature_details=source_features,
    )

    assert result["description"] == "A Nothing smartphone featuring the specifications you provided."
    assert result["features"] == "\n".join(
        f"- {line}" for line in source_features.splitlines()
    )
    assert result["generation_mode"] == "ai"


def test_structured_product_generation_preserves_every_supplied_feature(monkeypatch):
    monkeypatch.setattr(features, "redis_client", MemoryRedis())
    monkeypatch.setattr(features, "configured_providers", lambda: [
        AIProvider("groq", "test-key", "model", "https://provider.test/chat"),
    ])
    monkeypatch.setattr(
        features,
        "_complete_with_fallback",
        lambda *_args, **_kwargs: {
            "content": json.dumps({
                "description": "A scented candle with the listed details.",
                "features": "- Vanilla fragrance\n- Soy wax",
            })
        },
    )
    source_features = (
        "Fragrance: Vanilla\n"
        "Wax Type: Soy Wax\n"
        "Weight: 200 g\n"
        "Burning Time: Up to 40 hours\n"
        "Container: Glass Jar\n"
        "Color: RED\n"
        "Wick Type: Cotton\n"
        "Usage: Home decor, relaxation, gifting\n"
        "Special Feature: Smokeless design\n"
        "Package Contents: 12scented candle"
    )

    result = features.generate_product_content(
        "Scented candle",
        50,
        feature_details=source_features,
    )

    assert result["features"] == "\n".join(
        f"- {line}" for line in source_features.splitlines()
    )


@pytest.mark.parametrize("providers", [[], [
    AIProvider("groq", "test-key", "model", "https://provider.test/chat"),
]])
def test_product_content_generation_falls_back_to_only_supplied_details(
    monkeypatch,
    providers,
):
    monkeypatch.setattr(features, "redis_client", MemoryRedis())
    monkeypatch.setattr(features, "configured_providers", lambda: providers)
    monkeypatch.setattr(
        features,
        "_complete_with_fallback",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            features.AIServiceUnavailableError("All configured AI providers failed.")
        ),
    )

    result = features.generate_product_content(
        "Scented candle",
        50,
        category="Home & Kitchen",
        feature_details="Fragrance: Vanilla\nWax Type: Soy Wax\nWeight: 200 g",
    )

    assert result == {
        "description": (
            "Scented candle is listed with these supplied details: "
            "Fragrance: Vanilla; Wax Type: Soy Wax; Weight: 200 g."
        ),
        "features": "- Fragrance: Vanilla\n- Wax Type: Soy Wax\n- Weight: 200 g",
        "generation_mode": "source_fallback",
    }


def test_product_content_generation_without_ai_keeps_admin_description(monkeypatch):
    monkeypatch.setattr(features, "redis_client", MemoryRedis())
    monkeypatch.setattr(features, "configured_providers", lambda: [])

    result = features.generate_product_content(
        "Scented candle",
        50,
        feature_details="Fragrance: Vanilla",
        existing_description="Admin-written factual copy.",
    )

    assert result["description"] == "Admin-written factual copy."
    assert result["features"] == "- Fragrance: Vanilla"
    assert result["generation_mode"] == "source_fallback"


def test_product_search_agent_executes_only_the_whitelisted_catalogue_tool(monkeypatch):
    monkeypatch.setattr(features, "configured_providers", lambda: [
        AIProvider("mistral", "test-key", "model", "https://provider.test/chat"),
    ])
    monkeypatch.setattr(
        features,
        "retrieve_catalog_context",
        lambda _db, query: CatalogSearchResult(
            context=f"Query: {query}",
            sources=[{"product_id": 8, "name": "Water bottle", "price": 10.0, "stock": 4}],
        ),
    )
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        if calls == 1:
            assert payload["tools"][0]["function"]["name"] == "search_products"
            message = {
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "search_products", "arguments": '{"query":"reusable bottle"}'},
                }]
            }
        else:
            assert payload["messages"][-1]["role"] == "tool"
            assert "Query: reusable bottle" in payload["messages"][-1]["content"]
            message = {"content": "Water bottle [Product ID: 8]."}
        return httpx.Response(200, json={"choices": [{"message": message}]}, request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reply, result = features.run_product_search_agent(None, "Find a reusable bottle", client)

    assert reply == "Water bottle [Product ID: 8]."
    assert result.sources[0]["product_id"] == 8
    assert calls == 2


def test_semantic_route_reports_provider_outage_and_returns_paginated_success(monkeypatch):
    app.dependency_overrides[get_db] = lambda: None
    monkeypatch.setattr(
        products,
        "semantic_search_products",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            features.AIServiceUnavailableError("Embeddings are unavailable.")
        ),
    )
    try:
        unavailable = TestClient(app).get("/products/semantic-search?q=morning%20brew")
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == "Embeddings are unavailable."

        monkeypatch.setattr(
            products,
            "semantic_search_products",
            lambda *_args, **_kwargs: [SimpleNamespace(id=1), SimpleNamespace(id=2)],
        )
        success = TestClient(app).get("/products/semantic-search?q=morning%20brew&page=2&limit=1")
    finally:
        app.dependency_overrides.pop(get_db, None)

    payload = success.json()["data"]
    assert payload["total"] == 2
    assert payload["page"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == 2


def test_ai_endpoints_require_admin_for_description_generation_and_moderate_product_edits(monkeypatch):
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_db] = lambda: None
    monkeypatch.setattr(ai_chat, "generate_product_description", lambda *_args, **_kwargs: "A safe draft.")
    monkeypatch.setattr(
        products,
        "moderate_content",
        lambda _text: features.ModerationResult(False, "unsafe", "Rejected."),
    )
    try:
        generated = TestClient(app).post(
            "/ai/products/generate-description",
            json={"name": "Travel mug", "price": 18, "details": "Insulated cup"},
        )
        rejected = TestClient(app).post(
            "/products/",
            data={"name": "Unsafe product", "description": "unsafe description", "price": "10", "stock": "1"},
        )
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)

    assert generated.status_code == 200
    assert generated.json()["data"]["description"] == "A safe draft."
    assert rejected.status_code == 422
    assert "content moderation" in rejected.json()["detail"]


def test_structured_product_generation_endpoint_returns_editable_sections(monkeypatch):
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=1)
    limiter.enabled = True
    monkeypatch.setattr(
        ai_chat,
        "generate_product_content",
        lambda *_args, **_kwargs: {
            "description": "A grounded product description.",
            "features": "- 8GB RAM",
            "generation_mode": "ai",
        },
    )
    try:
        response = TestClient(app).post(
            "/ai/products/generate-content",
            json={
                "name": "Example laptop",
                "brand": "Example",
                "category": "Laptops",
                "price": 1200,
                "stock": 3,
                "features": "8GB RAM",
            },
        )
        assert response.status_code == 200
        assert response.json()["data"] == {
            "description": "A grounded product description.",
            "features": "- 8GB RAM",
            "generation_mode": "ai",
        }
        monkeypatch.setattr(
            ai_chat,
            "generate_product_content",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                features.AIServiceUnavailableError("All configured AI providers failed.")
            ),
        )
        unavailable = TestClient(app).post(
            "/ai/products/generate-content",
            json={"name": "Example laptop", "price": 1200},
        )
    finally:
        limiter.enabled = False
        app.dependency_overrides.pop(get_current_admin, None)
    assert unavailable.status_code == 503
    assert "providers failed" in unavailable.json()["detail"]


def test_product_content_endpoint_returns_grounded_draft_when_no_ai_provider_is_configured(monkeypatch):
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=1)
    monkeypatch.setattr(features, "configured_providers", lambda: [])
    monkeypatch.setattr(features, "redis_client", MemoryRedis())
    try:
        response = TestClient(app).post(
            "/ai/products/generate-content",
            json={
                "name": "Vanilla candle",
                "brand": "House Goods",
                "category": "Home & Kitchen",
                "price": 30,
                "stock": 2,
                "features": "Fragrance: Vanilla\nWax Type: Soy Wax",
            },
        )
    finally:
        app.dependency_overrides.pop(get_current_admin, None)

    assert response.status_code == 200
    assert response.json()["data"] == {
        "description": (
            "Vanilla candle is listed with these supplied details: "
            "Fragrance: Vanilla; Wax Type: Soy Wax."
        ),
        "features": "- Fragrance: Vanilla\n- Wax Type: Soy Wax",
        "generation_mode": "source_fallback",
    }


def test_description_generation_returns_rate_limit_headers_when_limiter_is_enabled(monkeypatch):
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=1)
    monkeypatch.setattr(ai_chat, "generate_product_description", lambda *_args, **_kwargs: "A safe draft.")
    limiter.enabled = True
    try:
        generated = TestClient(app).post(
            "/ai/products/generate-description",
            json={"name": "Travel mug", "price": 18},
        )
    finally:
        limiter.enabled = False
        app.dependency_overrides.pop(get_current_admin, None)

    assert generated.status_code == 200
    assert generated.headers["x-ratelimit-remaining"] == "4"
    assert generated.json()["data"]["description"] == "A safe draft."


def test_ai_rate_limit_key_uses_verified_user_identity_or_remote_address():
    token = create_access_token({"sub": "42"})
    request = SimpleNamespace(
        headers={"authorization": f"Bearer {token}"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert ai_rate_limit_key(request) == "ai-user:42"

    request.headers = {"authorization": "Bearer invalid"}
    assert ai_rate_limit_key(request) == "ai-ip:127.0.0.1"
