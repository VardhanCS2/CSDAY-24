import secrets
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient

from app.database.database import SessionLocal
from app.main import app
from app.core.rate_limit import limiter
from app.models.user import User


@pytest.fixture(autouse=True)
def disable_rate_limits_for_isolated_tests():
    enabled = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = enabled


@pytest.fixture
def client():

    return TestClient(app)



@pytest.fixture
def auth_headers(client):
    credentials = _new_credentials()
    registered = client.post("/auth/register", json=credentials)
    assert registered.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == credentials["email"]).first()
        assert user is not None
        user.role = "admin"
        db.commit()
    finally:
        db.close()

    response = client.post("/auth/login", json=credentials)
    assert response.status_code == 200
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def customer_headers(client):
    credentials = _new_credentials()
    registered = client.post("/auth/register", json=credentials)
    assert registered.status_code == 200
    response = client.post("/auth/login", json=credentials)
    assert response.status_code == 200
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_credentials():
    return _new_credentials()


def _new_credentials():
    return {
        "name": "Pytest User",
        "email": f"pytest-{uuid4().hex}@example.com",
        "password": secrets.token_urlsafe(24),
    }