from types import SimpleNamespace

import pytest

from app.api.deps import get_current_admin
from app.api.v1 import products as products_api
from app.database.database import get_db
from app.main import app
from app.services.product_service import ProductHasOrderHistoryError


def test_get_products(client):

    response = client.get(
        "/products/"
    )


    assert response.status_code == 200

    data = response.json()


    assert data["success"] is True



def test_create_product(client, auth_headers):

    response = client.post(
        "/products/",
        headers=auth_headers,
        data={
            "name": "Test Product",
            "description": "Testing product",
            "price": "1000",
            "stock": "10"
        }
    )


    assert response.status_code == 200

    product_id = response.json()["data"]["id"]
    deleted = client.delete(
        f"/products/{product_id}",
        headers=auth_headers
    )

    assert deleted.status_code == 200


def test_product_content_fields_are_saved_updated_and_searchable(client, auth_headers):
    created = client.post(
        "/products/",
        headers=auth_headers,
        data={
            "name": "Example programming laptop",
            "brand": "Example",
            "category": "Laptops",
            "description": "Portable computer.",
            "feature_details": "16GB RAM, 512GB storage",
            "features": "16GB RAM\n512GB storage",
            "specifications": '{"RAM":"16GB","Storage":"512GB"}',
            "price": "1200",
            "stock": "4",
        },
    )
    assert created.status_code == 200
    product_id = created.json()["data"]["id"]
    assert created.json()["data"]["specifications"] == {"RAM": "16GB", "Storage": "512GB"}

    try:
        updated = client.put(
            f"/products/{product_id}",
            headers=auth_headers,
            json={"features": "16GB RAM\n512GB SSD", "specifications": {"Memory": "16GB"}},
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["features"] == "16GB RAM\n512GB SSD"
        assert updated.json()["data"]["specifications"] == {"Memory": "16GB"}

        searched = client.get("/products/?search=512GB")
        assert searched.status_code == 200
        assert any(
            item["id"] == product_id
            for item in searched.json()["data"]["items"]
        )
        retrieved = client.get(f"/products/{product_id}")
        assert retrieved.status_code == 200
        assert retrieved.json()["data"]["category"] == "Electronics"
        assert retrieved.json()["data"]["specifications"] == {"Memory": "16GB"}
    finally:
        assert client.delete(f"/products/{product_id}", headers=auth_headers).status_code == 200


def test_product_search_normalizes_brand_aliases_and_compact_model_spacing(client, auth_headers):
    created = client.post(
        "/products/",
        headers=auth_headers,
        data={
            "name": "Motorola Edge 60",
            "brand": "Motorola",
            "category": "Mobiles",
            "description": "5G smartphone",
            "price": "30000",
            "stock": "2",
        },
    )
    assert created.status_code == 200
    product_id = created.json()["data"]["id"]

    try:
        for search_term in ("Moto Edge 60", "moto edge60", "MOTOROLA EDGE 60"):
            response = client.get("/products/", params={"search": search_term})
            assert response.status_code == 200
            assert any(item["id"] == product_id for item in response.json()["data"]["items"])
    finally:
        assert client.delete(f"/products/{product_id}", headers=auth_headers).status_code == 200


def test_category_catalog_is_stable_and_product_filters_include_legacy_categories(client, auth_headers):
    categories = client.get("/products/categories")
    assert categories.status_code == 200
    category_names = {item["name"] for item in categories.json()["data"]}
    assert {"Electronics", "Footwear", "Furniture", "Other"}.issubset(category_names)
    assert not {
        "Beauty & Personal Care",
        "Sports & Outdoors",
        "Grocery",
    }.intersection(category_names)

    created_ids = []
    for name, category in (
        ("Test mobile", "Mobiles"),
        ("Test shoes", "Footwear"),
    ):
        response = client.post(
            "/products/",
            headers=auth_headers,
            data={
                "name": name,
                "description": f"Test item in {category}",
                "category": category,
                "price": "10",
                "stock": "1",
            },
        )
        assert response.status_code == 200
        created_ids.append(response.json()["data"]["id"])

    try:
        electronics = client.get("/products/", params={"category": "Electronics", "limit": 100})
        footwear = client.get("/products/", params={"category": "Footwear", "limit": 100})
        assert electronics.status_code == 200
        assert footwear.status_code == 200
        assert created_ids[0] in {item["id"] for item in electronics.json()["data"]["items"]}
        assert created_ids[1] not in {item["id"] for item in electronics.json()["data"]["items"]}
        assert created_ids[1] in {item["id"] for item in footwear.json()["data"]["items"]}
    finally:
        for product_id in created_ids:
            assert client.delete(f"/products/{product_id}", headers=auth_headers).status_code == 200


def test_product_creation_does_not_infer_categories_from_description(client, auth_headers):
    created = client.post(
        "/products/",
        headers=auth_headers,
        data={
            "name": "Uncategorized device",
            "description": "A compact electronic gadget.",
            "price": "10",
            "stock": "1",
        },
    )

    assert created.status_code == 200
    product_id = created.json()["data"]["id"]
    assert created.json()["data"]["category"] is None
    assert created.json()["data"]["categories"] == []
    assert client.delete(f"/products/{product_id}", headers=auth_headers).status_code == 200


def test_product_creation_saves_only_admin_selected_categories_and_limits_to_three(client, auth_headers):
    created = client.post(
        "/products/",
        headers=auth_headers,
        data={
            "name": "Multi-category product",
            "description": "A shoe with a camera and book illustration.",
            "category": "Electronics",
            "categories": '["Electronics", "Footwear", "Accessories"]',
            "price": "10",
            "stock": "1",
        },
    )
    assert created.status_code == 200
    product_id = created.json()["data"]["id"]
    assert created.json()["data"]["categories"] == ["Electronics", "Footwear", "Accessories"]
    assert created.json()["data"]["category"] == "Electronics"

    try:
        for category in ("Electronics", "Footwear", "Accessories"):
            response = client.get(
                "/products/",
                params={"category": category, "limit": 100},
            )
            assert product_id in {item["id"] for item in response.json()["data"]["items"]}
    finally:
        assert client.delete(f"/products/{product_id}", headers=auth_headers).status_code == 200

    too_many = client.post(
        "/products/",
        headers=auth_headers,
        data={
            "name": "Too many categories",
            "categories": '["Electronics", "Footwear", "Clothing", "Furniture"]',
            "price": "10",
            "stock": "1",
        },
    )
    assert too_many.status_code == 422


def test_delete_product(client, auth_headers):

    created = client.post(
        "/products/",
        headers=auth_headers,
        data={
            "name": "Delete endpoint regression",
            "description": "Temporary test product",
            "price": "1",
            "stock": "1"
        }
    )

    assert created.status_code == 200
    product_id = created.json()["data"]["id"]

    response = client.delete(
        f"/products/{product_id}",
        headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_delete_product_with_order_history_returns_conflict(client, monkeypatch):
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_db] = lambda: None

    def reject_delete(_db, _product_id):
        raise ProductHasOrderHistoryError(
            "This product is part of an existing order and cannot be deleted. "
            "Set its stock to 0 to stop new sales while preserving order history."
        )

    monkeypatch.setattr(products_api, "remove_product", reject_delete)
    try:
        response = client.delete("/products/284")
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 409
    assert "existing order" in response.json()["detail"]
    assert "stock to 0" in response.json()["detail"]


def test_remove_product_rejects_product_referenced_by_order(monkeypatch):
    from app.services import product_service

    product = SimpleNamespace(id=284)

    class OrderItemQuery:
        def filter(self, _condition):
            return self

        def first(self):
            return SimpleNamespace(id=1)

    class ProductDB:
        def query(self, model):
            from app.models.order_item import OrderItem

            assert model is OrderItem.id
            return OrderItemQuery()

    monkeypatch.setattr(product_service, "get_product_by_id", lambda _db, _id: product)

    with pytest.raises(ProductHasOrderHistoryError, match="existing order"):
        product_service.remove_product(ProductDB(), 284)


def test_product_image_url_validation_and_upload(client, auth_headers, monkeypatch):
    import app.api.v1.products as product_routes

    created = client.post(
        "/products/",
        headers=auth_headers,
        data={
            "name": "Product image validation test",
            "description": "A product with a validated remote image.",
            "price": "12.50",
            "stock": "3",
            "image_url": "https://images.example.test/product.jpg",
        },
    )
    assert created.status_code == 200
    product_id = created.json()["data"]["id"]
    assert created.json()["data"]["image_url"] == "https://images.example.test/product.jpg"

    try:
        invalid_create = client.post(
            "/products/",
            headers=auth_headers,
            data={
                "name": "Invalid image URL test",
                "price": "1",
                "stock": "1",
                "image_url": "javascript:alert(1)",
            },
        )
        assert invalid_create.status_code == 400

        updated = client.put(
            f"/products/{product_id}",
            headers=auth_headers,
            json={"image_url": "https://images.example.test/updated.jpg"},
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["image_url"] == "https://images.example.test/updated.jpg"

        invalid_update = client.put(
            f"/products/{product_id}",
            headers=auth_headers,
            json={"image_url": "file:///etc/passwd"},
        )
        assert invalid_update.status_code == 400

        monkeypatch.setattr(product_routes, "save_image", lambda _image: "/uploads/products/test-upload.webp")
        uploaded = client.post(
            f"/products/{product_id}/image",
            headers=auth_headers,
            files={"image": ("test.webp", b"image bytes", "image/webp")},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["data"]["image_url"] == "/uploads/products/test-upload.webp"
    finally:
        deleted = client.delete(f"/products/{product_id}", headers=auth_headers)
        assert deleted.status_code == 200


def test_product_image_rejects_invalid_and_oversized_uploads(client, auth_headers):
    product = client.post(
        "/products/",
        headers=auth_headers,
        data={"name": "Rejected image upload", "price": "1", "stock": "1"},
    )
    assert product.status_code == 200
    product_id = product.json()["data"]["id"]

    invalid = client.post(
        f"/products/{product_id}/image",
        headers=auth_headers,
        files={"image": ("fake.png", b"not an image", "image/png")},
    )
    oversized = client.post(
        f"/products/{product_id}/image",
        headers=auth_headers,
        files={"image": ("large.png", b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024), "image/png")},
    )

    assert invalid.status_code == 400
    assert oversized.status_code == 413
    assert client.delete(f"/products/{product_id}", headers=auth_headers).status_code == 200