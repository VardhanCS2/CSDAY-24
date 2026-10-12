import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.v1 import ai_chat
from app.database.database import get_db
from app.main import app
from app.services.ai_chat_service import (
    AIProvider,
    CatalogSearchResult,
    ProvidersUnavailableError,
    _hashed_embedding,
    _prompt_messages,
    configured_providers,
    greeting_response,
    retrieve_catalog_context,
    stream_completion,
)
from app.core.config import settings


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


@pytest.mark.parametrize("message", ["hi", "hii", "hlo", "hello!", "Hey there", "good morning", "hi bot"])
def test_greeting_response_handles_common_greetings(message):
    reply = greeting_response(message)

    assert reply is not None
    assert "shopping assistant" in reply


@pytest.mark.parametrize("message", ["hi phone", "show me laptops", "this is a good phone"])
def test_greeting_response_does_not_match_product_requests(message):
    assert greeting_response(message) is None


def test_hashed_product_embedding_is_normalized_and_repeatable():
    embedding = _hashed_embedding("Reusable glass bottle 500ml")

    assert len(embedding) == 384
    assert _hashed_embedding("Reusable glass bottle 500ml") == embedding
    assert sum(value * value for value in embedding) == pytest.approx(1.0)


def test_provider_selection_uses_configured_fallback_order(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ORDER", "mistral,groq,mistral,gemini")
    monkeypatch.setattr(settings, "AI_MISTRAL_API_KEY", "mistral-test")
    monkeypatch.setattr(settings, "AI_GROQ_API_KEY", "groq-test")
    monkeypatch.setattr(settings, "AI_GEMINI_API_KEY", None)

    providers = configured_providers()

    assert [provider.name for provider in providers] == ["mistral", "groq"]


def test_langchain_prompt_maps_history_to_openai_roles():
    messages = _prompt_messages(
        "Show me bottles",
        "[Product ID: 12]\nProduct: Water bottle",
        [("user", "I need something reusable"), ("assistant", "I can help with that.")],
    )

    assert [message["role"] for message in messages] == ["system", "user", "assistant", "user"]
    assert "[Product ID: 12]" in messages[0]["content"]
    assert messages[-1]["content"] == "Show me bottles"


def test_chroma_retrieval_indexes_catalogue_chunks_and_product_citations(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=12,
            name="Reusable glass bottle",
            description="A lightweight water bottle made from durable glass. " * 40,
            price=24.5,
            stock=8,
        )
    ]
    products.extend(
        SimpleNamespace(
            id=product_id,
            name=f"Decorative ceramic plate {product_id}",
            description="Hand-painted tableware for serving dinner and dessert.",
            price=18.0,
            stock=2,
        )
        for product_id in range(13, 21)
    )

    search_result = retrieve_catalog_context(FakeProductDB(products), "reusable glass bottle")

    assert "[Product ID: 12]" in search_result.context
    assert "Price: 24.50" in search_result.context
    assert "Stock available: 8" in search_result.context
    assert search_result.sources[0] == {
        "product_id": 12,
        "name": "Reusable glass bottle",
        "price": 24.5,
        "stock": 8,
    }

    collection = ai_chat_service._catalog_collection
    indexed_ids = collection.get(include=["metadatas"])["ids"]
    assert sum(document_id.startswith("product-12-") for document_id in indexed_ids) > 1

    products[0].description = "A reusable water bottle made from durable glass."
    retrieve_catalog_context(FakeProductDB(products), "reusable glass bottle")
    indexed_ids = collection.get(include=["metadatas"])["ids"]
    assert [document_id for document_id in indexed_ids if document_id.startswith("product-12-")] == ["product-12-0"]


def test_catalog_retrieval_respects_mobile_synonyms_price_and_laptop_category(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(id=product_id, name=name, description=description, price=price, stock=5)
        for product_id, name, description, price in [
            (1, "Phone A", "Android smartphone", 30000),
            (2, "Phone B", "Android smartphone", 35000),
            (3, "Phone C", "Android smartphone", 40000),
            (4, "Phone D", "Android smartphone", 45000),
            (5, "Phone E", "Android smartphone", 49999),
            (6, "Phone F", "Android smartphone", 60000),
            (7, "Laptop A", "Windows laptop computer", 40000),
            (8, "Laptop B", "Windows laptop computer", 50000),
            (9, "Laptop C", "Windows laptop computer", 70000),
            (10, "Candle", "Home decoration", 100),
        ]
    ]

    mobile_result = retrieve_catalog_context(
        FakeProductDB(products),
        "show me mobiles under 50000",
    )
    assert len(mobile_result.sources) == 5
    assert all(source["price"] <= 50000 for source in mobile_result.sources)
    assert all("Phone" in source["name"] for source in mobile_result.sources)
    assert "Laptop" not in mobile_result.context

    laptop_result = retrieve_catalog_context(FakeProductDB(products), "show me laptops")
    assert {source["name"] for source in laptop_result.sources} == {"Laptop A", "Laptop B", "Laptop C"}
    assert "Candle" not in laptop_result.context


def test_broad_phone_budget_search_returns_all_matching_smartphones(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=product_id,
            name=name,
            description="Android smartphone with a capable camera.",
            price=price,
            stock=stock,
        )
        for product_id, name, price, stock in [
            (1, "Samsung Galaxy A", 30000, 5),
            (2, "Google Pixel A", 35000, 5),
            (3, "OnePlus Nord", 40000, 5),
            (4, "Xiaomi Note", 45000, 5),
            (5, "Vivo V", 50000, 5),
            (6, "OPPO Reno", 55000, 5),
            (7, "Realme GT", 60000, 5),
            (8, "Motorola Edge", 65000, 5),
            (9, "Apple iPhone Pro", 80000, 5),
            (10, "Nokia Phone", 20000, 0),
            (11, "Digital camera", 25000, 5),
            (12, "Travel laptop", 45000, 5),
        ]
    ]
    products[10].description = "Digital camera with an advanced lens."
    products[11].description = "Portable laptop with a high-resolution camera."

    result = retrieve_catalog_context(FakeProductDB(products), "phones under 70000")

    assert len(result.sources) == 8
    assert all(source["price"] <= 70000 and source["stock"] > 0 for source in result.sources)
    assert all(source["name"] not in {"Digital camera", "Travel laptop", "Apple iPhone Pro", "Nokia Phone"} for source in result.sources)
    assert result.reply is not None
    assert result.reply.count("[Product ID:") == 8
    assert "Samsung Galaxy A" in result.reply
    assert "Motorola Edge" in result.reply
    assert "Digital camera" not in result.reply


def test_catalog_retrieval_returns_under_budget_same_category_match(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(id=1, name="Everyday shoes", description="Comfortable walking shoes.", price=1000, stock=4),
        SimpleNamespace(id=2, name="Travel bag", description="A durable carry-on bag.", price=2000, stock=3),
    ]

    result = retrieve_catalog_context(FakeProductDB(products), "give me shoes under 4000")

    assert result.reply is not None
    assert "Everyday shoes" in result.reply
    assert "[Product ID: 1]" in result.reply
    assert [source["name"] for source in result.sources] == ["Everyday shoes"]
    assert all(source["price"] <= 4000 for source in result.sources)
    assert "Travel bag" not in result.context


def test_catalog_retrieval_only_offers_same_category_over_budget_alternatives(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(id=1, name="Everyday shoes", description="Comfortable shoes.", price=5000, stock=4),
        SimpleNamespace(id=2, name="Travel bag", description="A durable carry-on bag.", price=2000, stock=3),
    ]

    result = retrieve_catalog_context(FakeProductDB(products), "give me shoes under 4000")

    assert result.reply is not None
    assert "under ₹4,000" in result.reply
    assert result.source_label == "Same-category options over budget"
    assert [source["name"] for source in result.sources] == ["Everyday shoes"]
    assert "Travel bag" not in result.context


def test_catalog_does_not_claim_category_is_over_budget_when_only_request_detail_misses(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(id=1, name="Everyday shoes", description="Comfortable casual shoes.", price=1000, stock=4),
        SimpleNamespace(id=2, name="Formal shoes", description="Leather formal shoes.", price=5000, stock=4),
    ]

    result = retrieve_catalog_context(FakeProductDB(products), "formal shoes under 4000")

    assert result.sources == []
    assert result.reply is not None
    assert "couldn't find a product matching your request" in result.reply
    assert result.source_label == "Relevant catalogue sources"


def test_catalog_retrieval_does_not_confuse_product_features_with_missing_categories(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=1,
            name="Android phone",
            description="Includes a high-resolution camera.",
            price=30000,
            stock=4,
        )
    ]

    result = retrieve_catalog_context(FakeProductDB(products), "show me cameras")

    assert result.sources == []
    assert result.reply is not None
    assert "don't have cameras" in result.reply


def test_streaming_falls_back_when_a_provider_is_unavailable():
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/unavailable":
            return httpx.Response(429, request=request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"choices":[{"delta":{"content":"Grounded "}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"answer."}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
            request=request,
        )

    providers = [
        AIProvider("groq", "first-key", "first-model", "https://provider.test/unavailable"),
        AIProvider("gemini", "second-key", "second-model", "https://provider.test/available"),
    ]

    async def collect_response() -> list[str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return [chunk async for chunk in stream_completion([], providers, client)]

    assert asyncio.run(collect_response()) == ["Grounded ", "answer."]


def test_streaming_reports_failure_when_no_providers_are_configured():
    async def collect_response() -> list[str]:
        return [chunk async for chunk in stream_completion([], [])]

    with pytest.raises(ProvidersUnavailableError):
        asyncio.run(collect_response())


def test_ai_chat_endpoint_is_public_and_reports_missing_provider_configuration(monkeypatch):
    monkeypatch.setattr(ai_chat, "configured_providers", lambda: [])
    monkeypatch.setattr(
        ai_chat,
        "retrieve_catalog_context",
        lambda _db, _question: CatalogSearchResult(context="matching product context", sources=[]),
    )

    def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    try:
        response = TestClient(app).post("/ai/chat/stream", json={"message": "Find a bottle"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert "API key" in response.json()["detail"]


def test_ai_chat_endpoint_streams_sources_and_incremental_tokens(monkeypatch):
    monkeypatch.setattr(
        ai_chat,
        "configured_providers",
        lambda: [AIProvider("groq", "test-key", "test-model", "https://provider.test")],
    )
    monkeypatch.setattr(
        ai_chat,
        "retrieve_catalog_context",
        lambda _db, _question: CatalogSearchResult(
            context="[Product ID: 12]\nProduct: Reusable glass bottle",
            sources=[{"product_id": 12, "name": "Reusable glass bottle", "price": 24.5, "stock": 8}],
        ),
    )

    async def stream(_question, _context, _history, _providers):
        yield "A reusable "
        yield "glass bottle."

    monkeypatch.setattr(ai_chat, "stream_chat_response", stream)

    def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    try:
        response = TestClient(app).post("/ai/chat/stream", json={"message": "Find a bottle"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert events[0]["type"] == "sources"
    assert events[0]["label"] == "Relevant catalogue sources"
    assert events[1:3] == [
        {"type": "token", "text": "A reusable "},
        {"type": "token", "text": "glass bottle."},
    ]
    assert events[-1]["type"] == "done"


def test_ai_chat_endpoint_streams_catalogue_miss_without_a_provider(monkeypatch):
    monkeypatch.setattr(ai_chat, "configured_providers", lambda: [])
    monkeypatch.setattr(
        ai_chat,
        "retrieve_catalog_context",
        lambda _db, _question: CatalogSearchResult(
            context="",
            sources=[],
            reply="Sorry, we don't have cameras in our catalogue right now. Can I help you with another product?",
        ),
    )

    def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    try:
        response = TestClient(app).post("/ai/chat/stream", json={"message": "show me cameras"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert response.status_code == 200
    assert events[0] == {"type": "sources", "sources": [], "label": "Relevant catalogue sources"}
    assert events[1]["type"] == "token"
    assert "don't have cameras" in events[1]["text"]
    assert events[-1]["type"] == "done"


def test_ai_chat_endpoint_replies_to_greeting_without_catalogue_or_provider(monkeypatch):
    monkeypatch.setattr(ai_chat, "configured_providers", lambda: [])

    def unexpected_catalogue_lookup(_db, _question):
        raise AssertionError("Greeting should not require catalogue retrieval")

    monkeypatch.setattr(ai_chat, "retrieve_catalog_context", unexpected_catalogue_lookup)

    def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    try:
        response = TestClient(app).post("/ai/chat/stream", json={"message": "hii"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert response.status_code == 200
    assert events[0]["type"] == "sources"
    assert events[0]["sources"] == []
    assert events[1]["type"] == "token"
    assert "shopping assistant" in events[1]["text"]
    assert events[-1]["type"] == "done"
