# E-commerce Backend

## Local Setup

Use Python 3.10 or later. PostgreSQL and Redis must be running before starting the API. Start from `.env.example`, copy it to the ignored `.env` file, and fill in local values. Never commit `.env` or place production secrets in source, tests, or frontend `VITE_*` variables.

The backend pins `bcrypt<4.1` because the current `passlib` release is incompatible with newer bcrypt versions and can fail password hashing during registration or login. Install dependencies from this backend's `requirements.txt` and restart the API after changing dependencies; do not rely on a different workspace virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `DATABASE_URL` to the local PostgreSQL database, generate a private `JWT_SECRET_KEY`, and configure Redis URLs for `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND`. The SMTP settings are required by the current settings model; order email work is currently logged by the Celery task. All secrets belong in the ignored `.env` file; never put private values in frontend `VITE_*` settings. The backend ignores unrelated keys in this shared file, including optional `LOCUST_*` load-test settings.

For Docker Compose, copy the repository-root `.env.example` to `.env` before running `docker compose up --build`. Compose requires non-empty `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `SMTP_USERNAME`, and `SMTP_PASSWORD` values and will fail rather than use fallback credentials. Use a URL-safe random PostgreSQL password because Compose inserts it into the database URL.

Set `CORS_ORIGINS` to a comma-separated list of exact frontend origins (including scheme and port), for example `http://localhost:5173,http://127.0.0.1:5173`. `ENVIRONMENT` identifies the deployment environment. Never use wildcard origins. The frontend uses `/api` and `/ws` through the Vite development proxy by default; production deployments should set `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` to their API and secure WebSocket endpoints.

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

In another terminal, start the Celery worker for email, invoice, and CSV-import tasks:

```powershell
celery -A app.celery.worker.celery_app worker --loglevel=info --pool=solo
```

API docs are available at `http://127.0.0.1:8000/docs`. Tests generate per-test users and connect to the configured database and Redis service:

```powershell
pytest -q
```

The checkout endpoint accepts an optional validated `shipping_address` object and stores it with the order. `alembic upgrade head` applies the nullable address column without invalidating existing orders or clients that still submit an empty order request.

The authenticated WebSocket endpoint is `/ws?token=<access-token>`. It accepts `ping` and `chat.send` events, forwards customer support messages to connected administrators, and routes administrator replies to one customer. Order creation and status changes publish `order.updated` and `notification` events only to the customer who owns that order. Administrators advance orders through `Pending` → `Packed` → `Shipped` → `Out for Delivery` → `Delivered` → `Completed` with `PATCH /orders/{order_id}/status` and a JSON `status` value; the API rejects skipped or out-of-order transitions. WebSocket connections use the same signed, expiring access JWTs as HTTP requests.

## API hardening and load testing

The API applies a 120-request/minute default limit per client IP, tighter limits for registration/login (5/minute), token refresh (10/minute), and order creation (20/minute). AI endpoints use authenticated user IDs when a valid access token is present, and the client IP for guests: chat and the product-search agent (8/minute), description generation (5/minute), semantic search (20/minute), and product create/update moderation (12/minute). `429` responses include rate-limit information. The default local limiter uses process memory; production must set `RATE_LIMIT_STORAGE_URI` to a shared Redis-compatible URL (for example a dedicated Redis database) so limits are consistent across workers. Do not trust client-supplied forwarded IP headers unless the reverse proxy is configured to strip and set them.

Response bodies over 500 bytes are gzip-compressed. Responses also include anti-sniffing, framing, referrer, and permissions-policy headers; dynamic API responses are not cached. Production startup rejects weak JWT secrets, wildcard CORS/host rules, and process-local rate-limit storage, and disables the API documentation and OpenAPI schema. SQL statement logging is disabled by default; set `SQLALCHEMY_ECHO=true` temporarily when debugging queries. Set `ALLOWED_HOSTS` and `CORS_ORIGINS` to exact deployment values and terminate TLS at the trusted reverse proxy.

Run Locust with up to 50 concurrent shoppers after starting the API and loading products:

```powershell
locust -f locustfile.py --host http://127.0.0.1:8000 --users 50 --spawn-rate 10 --run-time 5m --headless
```

The scenario browses/searches products and can exercise all specifically rate-limited endpoints: login, registration, token refresh, and order creation. To avoid re-entering settings in PowerShell, add your test account values to the ignored `ecommerce-backend/.env` file (copy the optional `LOCUST_*` keys from `.env.example`). The Locust file loads that `.env` automatically; environment variables already set in PowerShell take precedence. A successful login supplies tokens for refresh and authenticated requests.

Registration is disabled unless `LOCUST_ENABLE_REGISTRATION=true`; when enabled, it creates uniquely named test accounts using `LOCUST_PASSWORD`. Authenticated order requests use a high, presumed-nonexistent product ID by default to exercise the endpoint without consuming inventory. To create real test orders instead, set `LOCUST_ENABLE_ORDER_CREATION=true` and `LOCUST_PRODUCT_ID` to an in-stock test product ID; this will create orders and reduce stock. `LOCUST_PRODUCT_ID` also enables product-detail reads. Use only local test-account credentials; never commit `.env` or use production credentials.

All Locust users launched from one machine share the same client IP, and the limiter is keyed by client IP. Expect `429` responses when the test exceeds the configured per-route or global limits (login/register 5/minute, refresh 10/minute, order creation 20/minute, default 120/minute). Never use production credentials or run mutating load tests against a live store.

## Background jobs, search, and payments

Run `alembic upgrade head` after updating. The migration adds durable `background_jobs` and `chats` tables, a nullable order payment-method field, and (on PostgreSQL) `pg_trgm` plus GIN indexes for full-text and trigram product search. Product listing search accepts `search_mode=full_text`, `fuzzy`, or `hybrid`; non-PostgreSQL development/test dialects use a case-insensitive substring fallback.

- `POST /jobs/invoices/{order_id}` queues invoice creation; `GET /jobs/` and `GET /jobs/{job_id}` return persisted status, progress, errors, and results; `GET /jobs/invoices/{order_id}/download` serves the completed PDF after verifying order ownership.
- Invoice and CSV-import requests require a responding Celery worker; if none is available, the API returns HTTP 503 instead of leaving a job queued indefinitely. Job polling also reconciles Celery's completed, failed, and progress states with the persisted job row.
- Admins upload product CSV files to `POST /jobs/imports/products` (`name,price,stock` required; `description,image_url` optional; image URLs must be absolute HTTP(S) URLs; 10 MB maximum). Invalid rows are reported in the completed job result. The web process and Celery worker must share the backend's ignored `private_files/` directory.
- `GET /chats/` returns the authenticated customer's saved conversation; administrators may retrieve all conversations or filter with `customer_id`. WebSocket chat messages are written to `chats` before delivery.
- `POST /orders/` may include `items` for a direct purchase and `payment_method` (`card`, `upi`, or `cash_on_delivery`). A direct purchase does not clear or change the Redis cart. Checkout is a demo only: card/UPI details are validated in the browser and are never sent to or stored by the backend.

Order creation locks requested product rows and loads them in one query; order history eagerly loads items and their products to avoid per-item N+1 queries.

Administrators can create products with either an uploaded image or a validated absolute HTTP(S) `image_url`; product updates accept `image_url`, and `POST /products/{product_id}/image` replaces an uploaded image. Uploaded images are capped at 5 MB, checked against their declared MIME type and file signature, and served from `/uploads/products/`.

## AI catalogue assistant

The public `POST /ai/chat/stream` endpoint streams Server-Sent Events and is separate from the authenticated `/chats/` WebSocket used for human support. It accepts `{"message":"...","history":[{"role":"user|assistant","content":"..."}]}` and emits JSON `data:` events with `sources`, incremental `token` text, `done`, or `error` types. Requests are limited to 8 per minute per verified user, or by client IP for guests; configure shared Redis rate-limit storage in production.

Set one or more backend-only keys in `.env`: `AI_GROQ_API_KEY`, `AI_GEMINI_API_KEY`, and/or `AI_MISTRAL_API_KEY`. The default order is `groq,gemini,mistral`; `AI_PROVIDER_ORDER` and each provider's `AI_*_MODEL` setting can be changed without code edits. Providers use their OpenAI-compatible streaming chat endpoints. On connection, rate-limit, or service errors before any answer text is sent, the next configured provider is tried. An interrupted response is reported rather than silently combining partial answers from different models. If no keys are configured, the endpoint returns HTTP 503 with a setup message. Free-tier availability and quotas are controlled by each provider and can change.

The backend rebuilds/updates a persistent ChromaDB collection from current product rows on each chat request, chunks descriptions with LangChain's recursive text splitter, and uses deterministic, normalized local feature-hash embeddings for chat context retrieval. This existing chat retrieval does not require a separate embedding API. The store defaults to the ignored `private_files/chroma` directory and can be moved with `AI_VECTOR_STORE_PATH`. A LangChain prompt constrains product claims to retrieved context, and the stream includes product IDs, names, prices, and stock as traceable source cards. The assistant is informational and is rate-limited because it is available to guests.

Common greetings such as “hi”, “hii”, “hlo”, “hello”, and “good morning” receive a friendly shopping-assistant introduction without requiring catalogue retrieval or a configured provider. Category and budget searches are checked against the catalogue before calling a provider. Smartphone category matching recognizes common product descriptions as well as phone names, while avoiding treating a product as a phone just because its description mentions a camera. Broad category-and-budget requests list every matching in-stock product in the retrieved result set, sorted by price, and include the matching source cards. In-budget matches are returned only from the requested category. If the category exists but no in-stock item meets the budget, the assistant can show up to three closest-priced options from that same category and labels them as over budget. If the category is missing or no suitable same-category option exists, it responds with a brief apology and asks whether the shopper wants another product; unrelated products are not suggested. These deterministic responses work even when no AI provider is configured.

## AI product features

Set one or more `AI_GROQ_API_KEY`, `AI_GEMINI_API_KEY`, or `AI_MISTRAL_API_KEY` values and order them with `AI_PROVIDER_ORDER` for chat, description generation, moderation, and the product-search agent. The admin product editor's **Generate with AI** action creates a draft; an administrator reviews and saves it. Product descriptions are checked before create/update, and generated copy is checked before it is returned. If configured moderation providers are unavailable, writes fail with HTTP 503 rather than silently bypassing moderation. When no moderation provider is configured, the service logs that it is using its limited local safety rules.

The storefront's **AI semantic search** uses real provider embeddings (not the token-hash vectors used for existing catalogue-grounded chat retrieval). Configure `AI_EMBEDDING_PROVIDER_ORDER` with Gemini and/or Mistral and set their corresponding embedding model variables (Gemini defaults to `gemini-embedding-001`; Mistral defaults to `mistral-embed`). Product vectors are persisted in Chroma under `AI_VECTOR_STORE_PATH`, indexed by provider/model, and refreshed only when product names or descriptions change. Query embeddings and completed AI responses are cached in Redis for `AI_RESPONSE_CACHE_TTL_SECONDS` (60–86400 seconds). Redis outages bypass caching and are logged; they do not produce fabricated cache hits. Semantic search returns HTTP 503 when no embedding provider is configured or all embedding providers fail. Existing keyword/hybrid search remains available without AI credentials.

`POST /ai/agent` demonstrates constrained function calling: the model may invoke only the application-owned `search_products` tool, its arguments are validated, the catalogue lookup runs server-side, and product facts are returned from that lookup. The frontend AI assistant has a switch for this agent mode. The regular chat remains streamed and has a retryable inline error state; an application error boundary offers a reload recovery state for render failures.

The backend tests mock all external AI HTTP calls. No live provider key is required to run the automated test suite. Product names/descriptions and shopper prompts sent to these features are processed by whichever external providers you configure; do not submit secrets or unrelated personal data.
