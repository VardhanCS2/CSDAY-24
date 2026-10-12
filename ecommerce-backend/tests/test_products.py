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