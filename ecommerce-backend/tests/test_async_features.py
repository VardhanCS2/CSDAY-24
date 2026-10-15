from app.celery import tasks
from app.api.v1 import ai_chat as ai_chat_api
from app.api.v1 import jobs as jobs_api
from app.database.database import SessionLocal
from app.models.background_job import BackgroundJob
from app.models.chat_message import ChatMessage
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.redis.cache import clear_cart
from app.utils.invoice import create_invoice_pdf


def test_ai_product_content_generation_runs_as_an_account_scoped_job(
    client,
    auth_headers,
    customer_headers,
    monkeypatch,
):
    from app.services import ai_features_service

    admin = client.get("/auth/me", headers=auth_headers).json()["data"]
    generated = {
        "description": "A grounded product draft.",
        "features": "- 8GB RAM",
        "generation_mode": "ai",
    }
    monkeypatch.setattr(ai_chat_api, "require_celery_worker", lambda: None)
    monkeypatch.setattr(ai_features_service, "generate_product_content", lambda *_args, **_kwargs: generated)
    monkeypatch.setattr(
        tasks.generate_product_content_task,
        "apply_async",
        lambda args, task_id: tasks.generate_product_content_task.apply(args=args, task_id=task_id),
    )

    response = client.post(
        "/ai/products/generate-content/jobs",
        headers=auth_headers,
        json={
            "name": "Example phone",
            "price": 100,
            "stock": 2,
            "brand": "Example",
            "category": "Electronics",
            "features": "8GB RAM",
            "existing_description": None,
        },
    )
    assert response.status_code == 200
    job_id = response.json()["data"]["id"]
    job_response = client.get(f"/jobs/{job_id}", headers=auth_headers)
    assert job_response.status_code == 200
    assert job_response.json()["data"]["status"] == "completed"
    assert job_response.json()["data"]["result"] == generated
    assert client.get(f"/jobs/{job_id}", headers=customer_headers).status_code == 404

    db = SessionLocal()
    try:
        db.query(BackgroundJob).filter(BackgroundJob.id == job_id).delete()
        db.commit()
    finally:
        db.close()


def test_invoice_job_runs_and_download_is_authenticated(client, auth_headers, customer_headers, monkeypatch):
    profile = client.get("/auth/me", headers=auth_headers).json()["data"]
    db = SessionLocal()
    order = Order(user_id=profile["id"], total_amount=18.5, status="Pending", payment_method="card")
    db.add(order)
    db.commit()
    db.refresh(order)
    order_id = order.id
    db.close()

    def run_task(args, task_id):
        return tasks.generate_invoice.apply(args=args, task_id=task_id)

    monkeypatch.setattr(jobs_api.celery_app.control, "ping", lambda **_kwargs: [{"worker": {"ok": "pong"}}])
    monkeypatch.setattr(tasks.generate_invoice, "apply_async", run_task)
    response = client.post(f"/jobs/invoices/{order_id}", headers=auth_headers)
    assert response.status_code == 200
    job_id = response.json()["data"]["id"]

    status_response = client.get(f"/jobs/{job_id}", headers=auth_headers)
    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "completed"
    assert status_response.json()["data"]["progress"] == 100
    download = client.get(f"/jobs/invoices/{order_id}/download", headers=auth_headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF-1.4")
    assert b"(Method: Card) Tj" in download.content
    assert b"(Status: Demo only; no payment was processed) Tj" in download.content
    assert client.get(f"/jobs/{job_id}").status_code == 401
    assert client.get(f"/jobs/{job_id}", headers=customer_headers).status_code == 404

    db = SessionLocal()
    try:
        db.query(BackgroundJob).filter(BackgroundJob.id == job_id).delete()
        db.query(Order).filter(Order.id == order_id).delete()
        db.commit()
    finally:
        db.close()
        (tasks.PRIVATE_FILES / f"invoice-{order_id}.pdf").unlink(missing_ok=True)


def test_invoice_pdf_keeps_large_orders_across_multiple_pages():
    pdf = create_invoice_pdf([f"Line item {index}" for index in range(60)])
    assert b"/Count 2" in pdf
    assert b"(Line item 59) Tj" in pdf


def test_job_list_reconciles_completed_celery_result(client, auth_headers, monkeypatch):
    profile = client.get("/auth/me", headers=auth_headers).json()["data"]
    db = SessionLocal()
    job = BackgroundJob(
        id="reconcile-completed-job",
        user_id=profile["id"],
        task_type="product_import",
        status="queued",
    )
    db.add(job)
    db.commit()
    db.close()

    class CompletedResult:
        state = "SUCCESS"
        result = {
            "progress": 100,
            "result": {"imported": 2, "processed": 2, "error_count": 0},
        }

    job_id = "reconcile-completed-job"
    async_result = jobs_api.AsyncResult
    monkeypatch.setattr(
        jobs_api,
        "AsyncResult",
        lambda result_id, app=None: CompletedResult() if result_id == job_id else async_result(result_id, app=app),
    )
    try:
        response = client.get("/jobs/", headers=auth_headers)
        assert response.status_code == 200
        found = next(item for item in response.json()["data"] if item["id"] == job_id)
        assert found["status"] == "completed"
        assert found["progress"] == 100
        assert found["result"]["imported"] == 2

        db = SessionLocal()
        persisted = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).one()
        assert persisted.status == "completed"
        db.delete(persisted)
        db.commit()
        db.close()
    finally:
        db = SessionLocal()
        db.query(BackgroundJob).filter(BackgroundJob.id == job_id).delete()
        db.commit()
        db.close()


def test_job_creation_fails_fast_without_a_celery_worker(client, auth_headers, monkeypatch):
    monkeypatch.setattr(jobs_api.celery_app.control, "ping", lambda **_kwargs: [])
    response = client.post(
        "/jobs/imports/products",
        headers=auth_headers,
        files={"file": ("products.csv", b"name,price,stock\nMug,10,1\n", "text/csv")},
    )
    assert response.status_code == 503
    assert "No Celery worker is running" in response.json()["detail"]


def test_csv_import_job_reports_progress_results_and_invalid_rows(client, auth_headers, monkeypatch):
    def run_task(args, task_id):
        return tasks.import_products_csv.apply(args=args, task_id=task_id)

    monkeypatch.setattr(jobs_api.celery_app.control, "ping", lambda **_kwargs: [{"worker": {"ok": "pong"}}])
    monkeypatch.setattr(tasks.import_products_csv, "apply_async", run_task)
    response = client.post(
        "/jobs/imports/products",
        headers=auth_headers,
        files={
            "file": (
                "products.csv",
                b"name,description,price,stock,image_url\nImport test mug,Stoneware,12.50,8,https://images.unsplash.com/photo-1602143407151-7111542de6e8\nInvalid price,No price,wrong,1,https://images.unsplash.com/photo-1602143407151-7111542de6e8\nInvalid image,No image,12.50,1,not-a-url\n",
                "text/csv",
            )
        },
    )
    assert response.status_code == 200
    job_id = response.json()["data"]["id"]
    job = client.get(f"/jobs/{job_id}", headers=auth_headers).json()["data"]
    assert job["status"] == "completed"
    assert job["progress"] == 100
    assert job["result"]["imported"] == 1
    assert job["result"]["processed"] == 3
    assert job["result"]["error_count"] == 2
    assert job["result"]["errors"] == [
        "Row 3: could not convert string to float: 'wrong'",
        "Row 4: image_url must be an absolute http or https URL",
    ]

    db = SessionLocal()
    try:
        imported_product = db.query(Product).filter(Product.name == "Import test mug").one()
        assert imported_product.image_url == "https://images.unsplash.com/photo-1602143407151-7111542de6e8"
        db.query(Product).filter(Product.name == "Import test mug").delete()
        db.query(BackgroundJob).filter(BackgroundJob.id == job_id).delete()
        db.commit()
    finally:
        db.close()


def test_full_text_and_fuzzy_product_search(client, auth_headers):
    profile = client.get("/auth/me", headers=auth_headers).json()["data"]
    db = SessionLocal()
    product = Product(
        name="Apple iPhone 16",
        description="A fast smartphone",
        price=20,
        stock=5,
        owner_id=profile["id"],
    )
    laptop = Product(
        name="Lenovo ThinkPad Laptop",
        description="Portable laptop computer",
        price=30,
        stock=5,
        owner_id=profile["id"],
    )
    basket = Product(
        name="Basket",
        description="Handwoven everyday storage",
        price=25,
        stock=5,
        owner_id=profile["id"],
    )
    db.add_all([product, laptop, basket])
    db.commit()
    product_id, laptop_id, basket_id = product.id, laptop.id, basket.id
    db.close()
    try:
        full_text = client.get("/products/", params={"search": "handwoven", "search_mode": "full_text"})
        assert full_text.status_code == 200
        assert basket_id in [item["id"] for item in full_text.json()["data"]["items"]]

        fuzzy = client.get("/products/", params={"search": "baskte", "search_mode": "fuzzy"})
        assert fuzzy.status_code == 200
        assert basket_id in [item["id"] for item in fuzzy.json()["data"]["items"]]

        partial = client.get("/products/", params={"search": "bask"})
        assert partial.status_code == 200
        assert basket_id in [item["id"] for item in partial.json()["data"]["items"]]

        related = client.get("/products/", params={"search": "woven baskt"})
        assert related.status_code == 200
        assert basket_id in [item["id"] for item in related.json()["data"]["items"]]

        misspelled_iphone = client.get("/products/", params={"search": "iphne"})
        assert product_id in [item["id"] for item in misspelled_iphone.json()["data"]["items"]]

        misspelled_laptop = client.get("/products/", params={"search": "leptop"})
        assert laptop_id in [item["id"] for item in misspelled_laptop.json()["data"]["items"]]
    finally:
        db = SessionLocal()
        db.query(Product).filter(Product.id.in_([product_id, laptop_id, basket_id])).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_direct_purchase_creates_order_without_clearing_existing_cart(client, auth_headers):
    profile = client.get("/auth/me", headers=auth_headers).json()["data"]
    db = SessionLocal()
    product = Product(
        name="Direct checkout test",
        description="One-time purchase",
        price=9.5,
        stock=10,
        owner_id=profile["id"],
    )
    db.add(product)
    db.commit()
    product_id = product.id
    db.close()

    order_ids = []
    try:
        client.post("/cart/add", headers=auth_headers, params={"product_identifier": "1", "quantity": 1})
        for method in ("card", "upi", "cash_on_delivery"):
            response = client.post(
                "/orders/",
                headers=auth_headers,
                json={
                    "items": [{"product_id": product_id, "quantity": 1}],
                    "payment_method": method,
                },
            )
            assert response.status_code == 200
            assert response.json()["data"]["total_amount"] == 9.5
            assert response.json()["data"]["payment_method"] == method
            assert len(response.json()["data"]["items"]) == 1
            order_ids.append(response.json()["data"]["id"])
        remaining_cart = client.get("/cart/", headers=auth_headers).json()["data"]
        assert any(item["product_id"] == 1 for item in remaining_cart)
    finally:
        db = SessionLocal()
        try:
            if order_ids:
                db.query(OrderItem).filter(OrderItem.order_id.in_(order_ids)).delete(synchronize_session=False)
                db.query(Order).filter(Order.id.in_(order_ids)).delete(synchronize_session=False)
            db.query(Product).filter(Product.id == product_id).delete()
            db.commit()
        finally:
            db.close()
            clear_cart(profile["id"])


def test_chat_history_is_persisted_and_customer_scoped(client, auth_headers, customer_headers):
    customer = client.get("/auth/me", headers=customer_headers).json()["data"]
    admin = client.get("/auth/me", headers=auth_headers).json()["data"]
    db = SessionLocal()
    message = ChatMessage(
        sender_id=customer["id"],
        recipient_id=admin["id"],
        text="Saved support question",
    )
    db.add(message)
    db.commit()
    message_id = message.id
    db.close()
    try:
        customer_history = client.get("/chats/", headers=customer_headers)
        assert customer_history.status_code == 200
        saved_message = next(item for item in customer_history.json()["data"] if item["id"] == message_id)
        assert saved_message["text"] == "Saved support question"
        assert saved_message["recipient_id"] == admin["id"]

        admin_history = client.get("/chats/", headers=auth_headers)
        assert any(item["id"] == message_id for item in admin_history.json()["data"])
        conversations = client.get("/chats/conversations", headers=auth_headers)
        assert conversations.status_code == 200
        conversation = next(
            item for item in conversations.json()["data"]
            if item["customer_id"] == customer["id"]
        )
        assert conversation["customer_name"] == customer["name"]
        assert conversation["last_message"] == "Saved support question"
        assert conversation["last_sender_id"] == customer["id"]

        forbidden_inbox = client.get("/chats/conversations", headers=customer_headers)
        assert forbidden_inbox.status_code == 403
        forbidden = client.get(f"/chats/?customer_id={admin['id']}", headers=customer_headers)
        assert forbidden.status_code == 403
    finally:
        db = SessionLocal()
        db.query(ChatMessage).filter(ChatMessage.id == message_id).delete()
        db.commit()
        db.close()
