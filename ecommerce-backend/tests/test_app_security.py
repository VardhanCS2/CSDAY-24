from app.core.rate_limit import limiter


def test_api_responses_include_security_headers(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["cache-control"] == "no-store"


def test_large_api_responses_are_compressed(client):
    response = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"


def test_login_endpoint_enforces_rate_limit(client):
    limiter.reset()
    was_enabled = limiter.enabled
    limiter.enabled = True
    try:
        responses = [
            client.post(
                "/auth/login",
                json={"email": "not-a-user@example.com", "password": "not-a-password"},
            )
            for _ in range(6)
        ]
    finally:
        limiter.enabled = was_enabled

    assert [response.status_code for response in responses[:5]] == [401] * 5
    assert responses[5].status_code == 429


def test_successful_login_works_with_rate_limit_enabled(client, user_credentials):
    assert client.post("/auth/register", json=user_credentials).status_code == 200
    limiter.reset()
    was_enabled = limiter.enabled
    limiter.enabled = True
    try:
        response = client.post("/auth/login", json=user_credentials)
    finally:
        limiter.enabled = was_enabled
        limiter.reset()

    assert response.status_code == 200
    assert response.headers["x-ratelimit-limit"] == "5"
    assert "access_token" in response.json()["data"]


def test_default_rate_limit_applies_to_unannotated_routes(client):
    limiter.reset()
    was_enabled = limiter.enabled
    limiter.enabled = True
    try:
        responses = [client.get("/") for _ in range(121)]
    finally:
        limiter.enabled = was_enabled

    assert all(response.status_code == 200 for response in responses[:120])
    assert responses[120].status_code == 429
