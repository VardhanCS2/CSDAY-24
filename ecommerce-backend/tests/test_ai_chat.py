import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_optional_current_user
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
            categories=["Home & Kitchen"],
        )
    ]
    products.extend(
        SimpleNamespace(
            id=product_id,
            name=f"Decorative ceramic plate {product_id}",
            description="Hand-painted tableware for serving dinner and dessert.",
            price=18.0,
            stock=2,
            categories=["Home & Kitchen"],
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
        "image_url": None,
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
        SimpleNamespace(
            id=product_id,
            name=name,
            description=description,
            price=price,
            stock=5,
            categories=["Home & Kitchen"] if name == "Candle" else ["Electronics"],
        )
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


def test_catalogue_context_includes_saved_brand_features_and_specifications(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    product = SimpleNamespace(
        id=44,
        name="Example mobile",
        brand="Example",
        category="Mobiles",
        categories=["Electronics"],
        description="A smartphone.",
        feature_details="256GB storage, OLED display",
        features="256GB storage\nOLED display",
        specifications={"Storage": "256GB", "Display": "OLED"},
        price=400,
        stock=2,
    )

    result = retrieve_catalog_context(FakeProductDB([product]), "Show mobiles with 256GB storage")

    assert result.sources[0]["product_id"] == 44
    assert "Brand: Example" in result.context
    assert "Category: Mobiles" in result.context
    assert "256GB storage" in result.context
    assert '"Storage": "256GB"' in result.context


def test_category_retrieval_uses_saved_product_category_without_description_false_matches(
    tmp_path,
    monkeypatch,
):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=1,
            name="Apple iPhone 16",
            category="Electronics",
            categories=[],
            description="A smartphone for everyday use.",
            price=50000,
            stock=5,
        ),
        SimpleNamespace(
            id=2,
            name="Bluetooth headset",
            category="Electronics",
            categories=["Electronics"],
            description="A headset compatible with smartphones.",
            price=2000,
            stock=5,
        ),
        SimpleNamespace(
            id=4,
            name="Wireless AirPods",
            category="Electronics",
            categories=["Electronics", "Accessories"],
            description="Wireless earbuds compatible with iPhone and iPad devices.",
            price=3000,
            stock=5,
        ),
        SimpleNamespace(
            id=3,
            name="Scented candles",
            category="Home & Kitchen",
            categories=[],
            description="A fragrance product for the home.",
            price=500,
            stock=5,
        ),
    ]

    mobile_result = retrieve_catalog_context(FakeProductDB(products), "show me mobiles")
    candle_result = retrieve_catalog_context(FakeProductDB(products), "show me candles")

    assert [source["product_id"] for source in mobile_result.sources] == [1]
    assert [source["product_id"] for source in candle_result.sources] == [3]
    assert "Bluetooth headset" not in mobile_result.context
    assert "Wireless AirPods" not in mobile_result.context


def test_broad_category_search_returns_all_matching_products_beyond_default_context_limit(
    tmp_path,
    monkeypatch,
):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=product_id,
            name=f"Phone {product_id}",
            category="Electronics",
            categories=["Electronics"],
            description="A smartphone with everyday features.",
            price=10000 + product_id,
            stock=5,
        )
        for product_id in range(1, 12)
    ]

    result = retrieve_catalog_context(FakeProductDB(products), "show me mobiles")

    assert len(result.sources) == 11
    assert "[Product ID: 11]" in (result.reply or "")


def test_natural_language_product_lookup_handles_stools_lenovo_and_missing_redmi_model(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=1, name="Oakwood Stool", description="Compact timber seating for a kitchen.",
            price=80, stock=3, image_url="/app/uploads/stool.jpg", categories=["Furniture"],
        ),
        SimpleNamespace(
            id=2, name="Lenovo ThinkPad T14", description="Business laptop with a durable keyboard.",
            price=1200, stock=2, image_url=None, categories=["Electronics"],
        ),
        SimpleNamespace(
            id=3, name="Redmi Note 13", description="Android mobile phone with a large display.",
            price=250, stock=4, image_url=None, categories=["Electronics"],
        ),
    ]

    stool_result = retrieve_catalog_context(FakeProductDB(products), "I want to know about stools")
    thinkpad_result = retrieve_catalog_context(FakeProductDB(products), "Tell me about Lenovo ThinkPad")
    missing_result = retrieve_catalog_context(FakeProductDB(products), "Tell me about Redmi Note 5")
    mobile_result = retrieve_catalog_context(FakeProductDB(products), "Show all available mobiles")

    assert [source["name"] for source in stool_result.sources] == ["Oakwood Stool"]
    assert [source["name"] for source in thinkpad_result.sources] == ["Lenovo ThinkPad T14"]
    assert thinkpad_result.sources[0]["image_url"] is None
    assert "exact match" in (missing_result.reply or "")
    assert "Redmi Note 13" in (missing_result.reply or "")
    assert "Redmi Note 13" in missing_result.context
    assert "Redmi Note 5" not in missing_result.context
    assert [source["name"] for source in mobile_result.sources] == ["Redmi Note 13"]


def test_exact_product_lookup_reports_out_of_stock_record_instead_of_calling_it_missing(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    product = SimpleNamespace(id=1, name="Lenovo ThinkPad X1", description="Business laptop.", price=1400, stock=0)

    result = retrieve_catalog_context(FakeProductDB([product]), "Tell me about Lenovo ThinkPad X1")

    assert [source["name"] for source in result.sources] == ["Lenovo ThinkPad X1"]
    assert result.sources[0]["stock"] == 0


def test_catalogue_stock_questions_return_actual_available_and_unavailable_products(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(id=1, name="In-stock stool", description="Wooden stool", price=80, stock=2),
        SimpleNamespace(id=2, name="Unavailable lamp", description="Desk lamp", price=60, stock=0),
    ]

    available = retrieve_catalog_context(FakeProductDB(products), "What products are in stock?")
    unavailable = retrieve_catalog_context(FakeProductDB(products), "Which products are currently unavailable?")

    assert [source["name"] for source in available.sources] == ["In-stock stool"]
    assert "product in stock" in (available.reply or "")
    assert [source["name"] for source in unavailable.sources] == ["Unavailable lamp"]
    assert "product currently unavailable" in (unavailable.reply or "")


def test_price_boundaries_support_above_and_between_queries(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(id=1, name="Phone 30", description="Android smartphone", price=30000, stock=2, categories=["Electronics"]),
        SimpleNamespace(id=2, name="Phone 40", description="Android smartphone", price=40000, stock=2, categories=["Electronics"]),
        SimpleNamespace(id=3, name="Phone 50", description="Android smartphone", price=50000, stock=2, categories=["Electronics"]),
    ]

    above = retrieve_catalog_context(FakeProductDB(products), "Show mobiles above ₹40,000")
    at_least = retrieve_catalog_context(FakeProductDB(products), "Show mobiles at least ₹40,000")
    between = retrieve_catalog_context(FakeProductDB(products), "Show mobiles between 30,000 and 40,000")

    assert [source["price"] for source in above.sources] == [50000.0]
    assert [source["price"] for source in at_least.sources] == [40000.0, 50000.0]
    assert [source["price"] for source in between.sources] == [30000.0, 40000.0]


def test_comparison_resolves_each_exact_model_and_does_not_substitute_variants(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    exact_products = [
        SimpleNamespace(id=1, name="Apple iPhone 16", description="128 GB storage", price=900, stock=2),
        SimpleNamespace(id=2, name="Apple iPhone 17", description=None, price=1000, stock=0),
        SimpleNamespace(id=3, name="Google Pixel 16", description="Android phone", price=800, stock=2),
    ]

    exact = retrieve_catalog_context(
        FakeProductDB(exact_products),
        "Compare iPhone 16 and iPhone 17",
    )
    assert [source["name"] for source in exact.sources] == ["Apple iPhone 16", "Apple iPhone 17"]
    assert "Catalogue comparison" in (exact.reply or "")
    assert "Not available in our catalogue" in (exact.reply or "")
    assert "[Product ID: 1]" in (exact.reply or "")
    assert "Out of stock" in (exact.reply or "")

    variant_only = retrieve_catalog_context(
        FakeProductDB([
            exact_products[0],
            SimpleNamespace(id=3, name="Apple iPhone 17 Pro Max", description="Premium model", price=1500, stock=1),
        ]),
        "Compare iPhone 16 and iPhone 17",
    )
    assert "exact catalogue match for: iPhone 17" in (variant_only.reply or "")
    assert "Apple iPhone 17 Pro Max" in (variant_only.reply or "")
    assert "not an exact match" in (variant_only.reply or "")


def test_comparison_parses_best_question_and_compares_games(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=1,
            name="Bottle",
            description="Reusable bottle.",
            features=None,
            specifications={},
            price=500,
            stock=10,
        ),
        SimpleNamespace(
            id=2,
            name="shoes",
            description="Everyday shoes.",
            features=None,
            specifications={},
            price=2000,
            stock=5,
        ),
        SimpleNamespace(
            id=403,
            name="uncharted game",
            description="Action-adventure game for PlayStation 5.",
            features="- Platform: PlayStation 5\n- Genre: Action-Adventure",
            specifications={},
            price=3400,
            stock=300,
        ),
        SimpleNamespace(
            id=404,
            name="amazing spiderman game",
            description="Superhero action game for console and PC.",
            features=None,
            specifications={},
            price=3000,
            stock=123,
        ),
    ]

    result = retrieve_catalog_context(
        FakeProductDB(products),
        "compare uncharted and spiderman witch one is best",
    )

    assert [source["product_id"] for source in result.sources] == [403, 404]
    assert "Catalogue comparison" in (result.reply or "")
    assert "Best value (based on listed price):** amazing spiderman game [Product ID: 404]" in (
        result.reply or ""
    )
    assert "costs ₹400.00 less" in (result.reply or "")
    assert "not provide enough comparable quality or performance information" in (
        result.reply or ""
    )


def test_comparison_normalizes_vivi_typo_and_resolves_both_phones(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=109,
            name="OnePlus 13",
            description="High-performance smartphone with a smooth display and fast charging.",
            features=None,
            specifications={},
            price=64999,
            stock=30,
        ),
        SimpleNamespace(
            id=112,
            name="Vivo V40",
            description="Stylish smartphone with a bright display and capable portrait camera.",
            features=None,
            specifications={},
            price=34999,
            stock=28,
        ),
    ]

    result = retrieve_catalog_context(
        FakeProductDB(products),
        "compare vivi v40 and oneplus 13",
    )

    assert [source["product_id"] for source in result.sources] == [112, 109]
    assert "Catalogue comparison" in (result.reply or "")
    assert "Best value (based on listed price):** Vivo V40 [Product ID: 112]" in (
        result.reply or ""
    )
    assert "costs ₹30,000.00 less" in (result.reply or "")


def test_comparison_with_ambiguous_product_name_returns_clarification_instead_of_500(
    tmp_path,
    monkeypatch,
):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=1,
            name="Lenovo ThinkPad E14",
            description="Business laptop.",
            price=1200,
            stock=2,
            categories=["Electronics"],
        ),
        SimpleNamespace(
            id=2,
            name="Dell ThinkPad E14",
            description="Business laptop.",
            price=1300,
            stock=2,
            categories=["Electronics"],
        ),
        SimpleNamespace(
            id=3,
            name="Apple iPhone 16",
            description="Smartphone.",
            price=900,
            stock=2,
            categories=["Electronics"],
        ),
    ]

    result = retrieve_catalog_context(
        FakeProductDB(products),
        "Compare ThinkPad E14 with Apple iPhone 16",
    )

    assert "couldn't verify an exact catalogue match for: ThinkPad E14" in (
        result.reply or ""
    )
    assert [source["name"] for source in result.sources] == [
        "Apple iPhone 16",
        "Lenovo ThinkPad E14",
        "Dell ThinkPad E14",
    ]
    assert "Catalogue comparison" not in (result.reply or "")


@pytest.mark.parametrize(
    "question",
    ["realme gt7 suggest me best phone", "REALME GT7 SUGGEST ME BEST PHONE"],
)
def test_compact_model_lookup_is_case_insensitive_and_prioritizes_real_catalogue_match(
    tmp_path,
    monkeypatch,
    question,
):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=114,
            name="Realme GT 7",
            brand="Realme",
            category="Mobiles",
            categories=["Electronics"],
            description="Android smartphone.",
            features="Display: AMOLED\nBattery: 5,000 mAh\nCharging: Fast charging",
            specifications={"RAM": "12 GB", "Storage": "256 GB"},
            price=42999,
            stock=3,
        ),
        SimpleNamespace(
            id=113,
            name="OPPO Reno 13",
            brand="OPPO",
            category="Mobiles",
            categories=["Electronics"],
            description="Android smartphone.",
            features="Display: AMOLED",
            specifications={},
            price=37999,
            stock=3,
        ),
    ]

    result = retrieve_catalog_context(
        FakeProductDB(products),
        question,
    )

    assert result.sources[0]["product_id"] == 114
    assert "Verified catalogue match for the requested product/model" in result.context
    assert "Realme GT 7 [Product ID: 114]** is an exact catalogue match" in (result.reply or "")
    assert "12 GB" in (result.reply or "")
    assert "lowest listed price" in (result.reply or "")


def test_product_comparison_uses_saved_features_and_specs_and_recommends_on_price(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=114,
            name="Realme GT 7",
            description="Android smartphone.",
            features="Display: AMOLED\nBattery: 5,000 mAh\nCharging: Fast charging",
            specifications={"RAM": "12 GB", "Storage": "256 GB"},
            price=42999,
            stock=3,
        ),
        SimpleNamespace(
            id=111,
            name="Nothing Phone 4",
            description="Android phone with transparent-inspired design.",
            features="Display: AMOLED\nBattery: 4,800 mAh\nCamera: 50 MP",
            specifications={"RAM": "8 GB", "Storage": "256 GB"},
            price=44999,
            stock=2,
        ),
    ]

    result = retrieve_catalog_context(
        FakeProductDB(products),
        "COMPARE REALME GT7 AND NOTHING PHONE 4",
    )

    assert [source["product_id"] for source in result.sources] == [114, 111]
    assert "| RAM | 12 GB | 8 GB |" in (result.reply or "")
    assert "| Battery | 5,000 mAh | 4,800 mAh |" in (result.reply or "")
    assert "| Charging | Fast charging | Not available in our catalogue |" in (result.reply or "")
    assert "**Best value (based on listed price):** Realme GT 7 [Product ID: 114]" in (
        result.reply or ""
    )
    assert "### Realme GT 7 — Product ID 114" in (result.reply or "")
    assert "[View Realme GT 7](/product/114)" in (result.reply or "")


@pytest.mark.parametrize(
    ("question", "expected_name"),
    [
        ("MOTOROLA EDGE 60", "Motorola Edge 60"),
        ("motorola edge 60", "Motorola Edge 60"),
        ("Moto Edge 60", "Motorola Edge 60"),
        ("moto edge60", "Motorola Edge 60"),
        ("APPLE IPHONE 16", "Apple iPhone 16"),
        ("Apple phone 16", "Apple iPhone 16"),
        ("i phone 16", "Apple iPhone 16"),
    ],
)
def test_catalogue_lookup_normalizes_configured_aliases_and_model_spacing(
    tmp_path,
    monkeypatch,
    question,
    expected_name,
):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(
            id=60,
            name="Motorola Edge 60",
            brand="Motorola",
            category="Mobiles",
            categories=["Electronics"],
            description="5G smartphone",
            price=30000,
            stock=2,
        ),
        SimpleNamespace(
            id=16,
            name="Apple iPhone 16",
            brand="Apple",
            category="Mobiles",
            categories=["Electronics"],
            description="iOS smartphone",
            price=70000,
            stock=2,
        ),
    ]

    result = retrieve_catalog_context(FakeProductDB(products), question)

    assert result.sources[0]["name"] == expected_name


def test_comparison_resolves_aliases_and_ignores_use_case_after_product_names(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(id=60, name="Motorola Edge 60", description="5G phone", price=30000, stock=2, categories=["Electronics"]),
        SimpleNamespace(id=7, name="Realme GT 7", description="Android phone", price=32000, stock=2, categories=["Electronics"]),
    ]

    result = retrieve_catalog_context(
        FakeProductDB(products),
        "Compare Moto Edge 60 with realme gt7 for camera",
    )

    assert [source["product_id"] for source in result.sources] == [60, 7]


def test_chatbot_uses_existing_hybrid_database_search_when_terms_do_not_match(
    tmp_path,
    monkeypatch,
):
    from app.services import ai_chat_service, product_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    product = SimpleNamespace(
        id=99,
        name="Endurance Mobile",
        brand="Example",
        category="Mobiles",
        categories=["Electronics"],
        description="Built for long days away from a charger.",
        features="Battery: 5,000 mAh",
        specifications={},
        price=25000,
        stock=2,
    )
    search_calls = []

    def hybrid_search(db, **kwargs):
        search_calls.append(kwargs)
        return {"items": [product]}

    monkeypatch.setattr(product_service, "get_all_products", hybrid_search)
    db = FakeProductDB([product])
    db.bind = object()

    result = retrieve_catalog_context(db, "show phones with good battery life")

    assert search_calls[0]["search_mode"] == "hybrid"
    assert result.sources[0]["product_id"] == 99


def test_category_recommendation_and_similar_follow_up_use_verified_products(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    products = [
        SimpleNamespace(id=1, name="Work Laptop", description="Portable laptop for office tasks.", price=900, stock=2, categories=["Electronics"]),
        SimpleNamespace(id=2, name="Travel Laptop", description="Portable laptop for office and travel.", price=800, stock=1, categories=["Electronics"]),
        SimpleNamespace(id=3, name="Wood Stool", description="Compact seating.", price=80, stock=3, categories=["Furniture"]),
    ]

    recommendation = retrieve_catalog_context(
        FakeProductDB(products),
        "Which laptop is best for programming?",
    )
    similar = retrieve_catalog_context(
        FakeProductDB(products),
        "Show products similar to this one",
        [("assistant", "Work Laptop [Product ID: 1]")],
    )

    assert {source["name"] for source in recommendation.sources} == {"Work Laptop", "Travel Laptop"}
    assert "Travel Laptop" in {source["name"] for source in similar.sources}
    assert "Work Laptop" not in {source["name"] for source in similar.sources}


def test_database_catalogue_search_survives_chroma_failure(tmp_path, monkeypatch):
    from app.services import ai_chat_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)

    def fail_vector_store():
        raise RuntimeError("vector store unavailable")

    monkeypatch.setattr(ai_chat_service, "_get_catalog_collection", fail_vector_store)
    result = retrieve_catalog_context(
        FakeProductDB([
            SimpleNamespace(id=1, name="Oak Stool", description="Wood seating", price=40, stock=2, categories=["Furniture"]),
        ]),
        "Tell me about stools",
    )

    assert [source["name"] for source in result.sources] == ["Oak Stool"]
    assert "Oak Stool" in result.context


def test_ai_semantic_candidates_are_checked_against_catalogue_records(tmp_path, monkeypatch):
    from app.services import ai_chat_service, ai_features_service

    monkeypatch.setattr(settings, "AI_VECTOR_STORE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "AI_GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai_chat_service, "_catalog_collection", None)
    monkeypatch.setattr(ai_chat_service, "_catalog_client", None)
    product = SimpleNamespace(
        id=7, name="Lenovo ThinkPad", description="Portable workstation.", price=900, stock=2,
        categories=["Electronics"],
    )
    monkeypatch.setattr(
        ai_features_service,
        "semantic_search_products",
        lambda _db, _query, **_filters: [product],
    )

    result = retrieve_catalog_context(FakeProductDB([product]), "Find a computer for coding")

    assert [source["product_id"] for source in result.sources] == [7]
    assert "Lenovo ThinkPad" in result.context


def test_empty_catalogue_returns_clear_response():
    result = retrieve_catalog_context(FakeProductDB([]), "What products are in stock?")

    assert result.sources == []
    assert "catalogue is empty" in (result.reply or "")


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
            categories=["Electronics"] if product_id <= 10 or product_id in (11, 12) else [],
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
        SimpleNamespace(id=1, name="Everyday shoes", description="Comfortable walking shoes.", price=1000, stock=4, categories=["Footwear"]),
        SimpleNamespace(id=2, name="Travel bag", description="A durable carry-on bag.", price=2000, stock=3, categories=["Accessories"]),
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
        SimpleNamespace(id=1, name="Everyday shoes", description="Comfortable shoes.", price=5000, stock=4, categories=["Footwear"]),
        SimpleNamespace(id=2, name="Travel bag", description="A durable carry-on bag.", price=2000, stock=3, categories=["Accessories"]),
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
        SimpleNamespace(id=1, name="Everyday shoes", description="Comfortable casual shoes.", price=1000, stock=4, categories=["Footwear"]),
        SimpleNamespace(id=2, name="Formal shoes", description="Leather formal shoes.", price=5000, stock=4, categories=["Footwear"]),
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


def test_ai_chat_endpoint_returns_catalogue_matches_without_provider_configuration(monkeypatch):
    monkeypatch.setattr(ai_chat, "configured_providers", lambda: [])
    monkeypatch.setattr(
        ai_chat,
        "retrieve_catalog_context",
        lambda _db, _question, _history=(): CatalogSearchResult(
            context="matching product context",
            sources=[{"product_id": 3, "name": "Bottle", "price": 12, "stock": 2}],
        ),
    )

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
    assert events[1]["type"] == "token"
    assert "Bottle" in events[1]["text"]
    assert "[Product ID: 3]" in events[1]["text"]
    assert events[-1]["type"] == "done"


def test_ai_chat_endpoint_uses_database_fallback_when_all_providers_fail(monkeypatch):
    monkeypatch.setattr(ai_chat, "get_cached_value", lambda _key: None)
    monkeypatch.setattr(ai_chat, "set_cached_value", lambda _key, _value: None)
    monkeypatch.setattr(
        ai_chat,
        "configured_providers",
        lambda: [AIProvider("groq", "test-key", "test-model", "https://provider.test")],
    )
    monkeypatch.setattr(
        ai_chat,
        "retrieve_catalog_context",
        lambda _db, _question, _history=(): CatalogSearchResult(
            context="[Product ID: 9]\nProduct: Lenovo ThinkPad",
            sources=[{"product_id": 9, "name": "Lenovo ThinkPad", "price": 1200, "stock": 2}],
        ),
    )

    async def fail_before_response(_question, _context, _history, _providers):
        raise ProvidersUnavailableError("provider unavailable")
        yield "unreachable"

    monkeypatch.setattr(ai_chat, "stream_chat_response", fail_before_response)

    def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    try:
        response = TestClient(app).post("/ai/chat/stream", json={"message": "Tell me about Lenovo ThinkPad"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert response.status_code == 200
    assert events[0]["type"] == "sources"
    assert events[1]["type"] == "token"
    assert "Lenovo ThinkPad" in events[1]["text"]
    assert "[Product ID: 9]" in events[1]["text"]
    assert events[-1]["type"] == "done"


def test_ai_chat_endpoint_streams_sources_and_incremental_tokens(monkeypatch):
    monkeypatch.setattr(ai_chat, "get_cached_value", lambda _key: None)
    monkeypatch.setattr(ai_chat, "set_cached_value", lambda _key, _value: None)
    monkeypatch.setattr(
        ai_chat,
        "configured_providers",
        lambda: [AIProvider("groq", "test-key", "test-model", "https://provider.test")],
    )
    monkeypatch.setattr(
        ai_chat,
        "retrieve_catalog_context",
        lambda _db, _question, _history=(): CatalogSearchResult(
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
        lambda _db, _question, _history=(): CatalogSearchResult(
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

    def unexpected_catalogue_lookup(_db, _question, _history=()):
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


@pytest.mark.parametrize("role", ["customer", "admin"])
def test_chatbot_allows_guest_and_supported_account_roles(role):
    def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    app.dependency_overrides[get_optional_current_user] = lambda: SimpleNamespace(id=21, role=role)
    try:
        response = TestClient(app).post("/ai/chat/stream", json={"message": "hello"})
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_optional_current_user, None)

    assert response.status_code == 200


def test_chatbot_rejects_unsupported_authenticated_roles():
    def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    app.dependency_overrides[get_optional_current_user] = lambda: SimpleNamespace(id=21, role="seller")
    try:
        response = TestClient(app).post("/ai/chat/stream", json={"message": "hello"})
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_optional_current_user, None)

    assert response.status_code == 403
    assert "Chatbot access" in response.json()["detail"]


def test_authenticated_chat_response_cache_is_scoped_to_account(monkeypatch):
    cache_keys: list[str] = []
    current_account = {"id": 21, "role": "customer"}
    monkeypatch.setattr(
        ai_chat,
        "retrieve_catalog_context",
        lambda _db, _question, _history=(): CatalogSearchResult(context="catalogue context", sources=[]),
    )
    monkeypatch.setattr(
        ai_chat,
        "configured_providers",
        lambda: [AIProvider("groq", "test-key", "test-model", "https://provider.test")],
    )
    monkeypatch.setattr(
        ai_chat,
        "get_cached_value",
        lambda key: cache_keys.append(key) or "Cached catalogue answer.",
    )
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_optional_current_user] = lambda: SimpleNamespace(**current_account)
    try:
        client = TestClient(app)
        first = client.post("/ai/chat/stream", json={"message": "Find a bottle"})
        current_account.update(id=22, role="admin")
        second = client.post("/ai/chat/stream", json={"message": "Find a bottle"})
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_optional_current_user, None)

    assert first.status_code == second.status_code == 200
    assert len(cache_keys) == 2
    assert cache_keys[0] != cache_keys[1]


def test_agent_endpoint_rejects_unsupported_authenticated_roles():
    def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    app.dependency_overrides[get_optional_current_user] = lambda: SimpleNamespace(id=21, role="seller")
    try:
        response = TestClient(app).post("/ai/agent", json={"message": "Find a bottle"})
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_optional_current_user, None)

    assert response.status_code == 403
