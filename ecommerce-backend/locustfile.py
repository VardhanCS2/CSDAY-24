import os
from pathlib import Path
from uuid import uuid4

from locust import HttpUser, between, task
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))


class StorefrontUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.email = os.getenv("LOCUST_EMAIL")
        self.password = os.getenv("LOCUST_PASSWORD")
        access_token = os.getenv("LOCUST_ACCESS_TOKEN")
        self.refresh_token = os.getenv("LOCUST_REFRESH_TOKEN")
        if access_token:
            self._set_access_token(access_token)

    def _set_access_token(self, access_token):
        self.client.headers.update({"Authorization": f"Bearer {access_token}"})

    def _update_tokens(self, response):
        token_data = response.json()["data"]
        self._set_access_token(token_data["access_token"])
        self.refresh_token = token_data["refresh_token"]

    @task(6)
    def browse_products(self):
        self.client.get("/products/", name="GET /products")

    @task(2)
    def search_products(self):
        self.client.get("/products/?search=everyday", name="GET /products?search")

    @task(1)
    def load_product_detail(self):
        product_id = os.getenv("LOCUST_PRODUCT_ID")
        if product_id and product_id.isdigit():
            self.client.get(f"/products/{product_id}", name="GET /products/{id}")

    @task(1)
    def load_customer_data(self):
        if "Authorization" in self.client.headers:
            self.client.get("/cart/", name="GET /cart")
            self.client.get("/orders/", name="GET /orders")

    @task(1)
    def login(self):
        if not self.email or not self.password:
            return

        response = self.client.post(
            "/auth/login",
            name="POST /auth/login",
            json={"email": self.email, "password": self.password},
        )
        if response.status_code == 200:
            self._update_tokens(response)

    @task(1)
    def register(self):
        if os.getenv("LOCUST_ENABLE_REGISTRATION", "").lower() != "true":
            return
        if not self.password:
            return

        self.client.post(
            "/auth/register",
            name="POST /auth/register",
            json={
                "name": "Locust Test User",
                "email": f"locust-{uuid4().hex}@example.test",
                "password": self.password,
            },
        )

    @task(1)
    def refresh_tokens(self):
        if not self.refresh_token:
            return

        response = self.client.post(
            "/auth/refresh",
            name="POST /auth/refresh",
            json={"refresh_token": self.refresh_token},
        )
        if response.status_code == 200:
            self._update_tokens(response)

    @task(1)
    def create_order(self):
        if "Authorization" not in self.client.headers:
            return

        create_real_order = (
            os.getenv("LOCUST_ENABLE_ORDER_CREATION", "").lower() == "true"
        )
        product_id = os.getenv("LOCUST_PRODUCT_ID") if create_real_order else None
        if create_real_order and (not product_id or not product_id.isdigit()):
            return

        requested_product_id = (
            int(product_id)
            if create_real_order
            else 9_223_372_036_854_775_807
        )
        self.client.post(
            "/orders/",
            name="POST /orders/",
            json={
                "items": [
                    {"product_id": requested_product_id, "quantity": 1}
                ]
            },
        )
