# E-commerce Frontend

## State Management

| Option | Strengths | Trade-offs | Fit here |
| --- | --- | --- | --- |
| React Context | Built into React; good for low-frequency values shared by a subtree | Provider value changes can rerender many consumers; async cache behavior must be built separately | Fine for small settings or theme state |
| Zustand | Small API, selector-based subscriptions, simple actions outside components | Requires an additional dependency and clear ownership boundaries | Chosen for authentication and the globally visible cart |
| Redux Toolkit | Explicit reducers, middleware, strong conventions and tooling for complex workflows | More structure and boilerplate than this store currently needs | Better fit if the app grows into many coordinated client-side workflows |

The app uses Zustand for client-owned session and cart state. TanStack Query owns remote data such as products, customer/admin orders, and the server cart; its cache is keyed by resource and user, kept fresh for 60 seconds, and invalidated after writes. The cart store mirrors the active user's query so the header count stays available across routes.

## Implemented Patterns

- Product listing uses `useInfiniteQuery`, the backend's existing page/limit contract, debounced search, and an `IntersectionObserver`. A load-more button remains as a keyboard-friendly fallback.
- Cart changes, checkout, order status transitions, product edits, and product removal optimistically update cached data. Failed requests restore the previous cache value.
- Query, debounce, and observer behavior live in custom hooks. Product cards are memoized; sorting and filter params use `useMemo`, and the add handler uses `useCallback`.
- Route pages are dynamically imported with `React.lazy` and `Suspense`.
- Product and admin-preview images use native lazy loading and asynchronous decoding. The storefront hero and product-detail lead image remain eager so lazy loading does not delay above-the-fold/Largest Contentful Paint content.
- API requests use the same-origin `/api` proxy. Do not put tokens, credentials, or private API keys in frontend source; browser-visible `VITE_*` values are public.

## Run

```sh
npm install
npm run dev
```

The frontend expects FastAPI on the Vite proxy target at `http://127.0.0.1:8000`; backend setup is in `../ecommerce-backend/README.md`.

Copy `.env.example` to `.env` to override the Vite proxy target or public storefront settings. `VITE_API_BASE_URL` is optional; leave it unset to use the same-origin `/api` proxy. The API docs link opens FastAPI's `/docs` directly; set `VITE_API_DOCS_URL` when the backend is hosted at a non-local address. Locale and currency can be changed with `VITE_LOCALE` and `VITE_CURRENCY`. Never place credentials or private keys in `VITE_*` variables.

## Type Safety, Checkout, And Tests

The complete React application is TypeScript with strict compiler checks. Shared API/model contracts are in `src/types/`, Zod validates registration, catalog changes, and delivery details, Zustand owns client-side session/cart state, and TanStack Query owns server data and cache invalidation.

Checkout posts validated delivery details and a demo payment method to `POST /orders/`. The product detail page's Buy now button opens `/payments` with a direct-purchase item, without changing the cart. Card and UPI fields are client-side demo fields only; no payment is processed and those values are never sent to the backend. Apply the migration before running the updated application:

```sh
cd ../ecommerce-backend
alembic upgrade head
```

The card and UPI values are validated in the browser only and are never persisted.

The Playwright suite covers catalog browsing and filtering, authentication, cart mutations, checkout and order history, admin order/product workflows, live notification/chat UI, and theme persistence. It intercepts API requests with stateful test doubles so the browser suite is repeatable and does not create data in a real store. In local runs `npm run test:e2e` launches a visible Chromium browser; `npm run test:e2e:ui` opens Playwright's interactive test runner, and `npm run test:e2e:headed` explicitly requests headed execution. CI runs the same suite headlessly.

Playwright generates isolated customer and admin `storageState` files for authenticated journeys, avoiding repeated sign-in while keeping sign-in and registration coverage anonymous. The app uses the authenticated `/ws` endpoint for live order notifications and support chat, refreshes expiring access tokens, sends ping/pong keepalives, and retries interrupted connections with capped exponential backoff. Chat history loads from and persists to the backend `chats` table. Configure `VITE_WS_BASE_URL` alongside `VITE_API_BASE_URL` when the production frontend and backend use separate origins.

### Realtime connection troubleshooting

- Keep both the FastAPI server and the frontend/API proxy running. In development, Vite proxies `/ws` to `API_PROXY_TARGET`; the proxy must support WebSocket upgrades.
- In production, set `VITE_WS_BASE_URL` to the backend origin (`wss://...` when served over HTTPS) and set backend `CORS_ORIGINS` to the exact frontend origin, including scheme and port.
- In browser DevTools → Network → WS, a successful connection has status `101`. A failed handshake (often shown as `403`) can indicate an expired/invalid access token or a rejected `Origin`; check that the refresh token is still valid and the frontend origin exactly matches `CORS_ORIGINS`.
- A connection refused or failed upgrade usually means the API is stopped, the proxy target is wrong, or the production WebSocket URL is incorrect. Restart the API after changing backend configuration.
- The client sends a ping every 25 seconds and reconnects if no pong arrives within 10 seconds; retries back off up to 30 seconds. When reporting a failure, include the WS request URL (without its token), handshake status, browser console error, and corresponding API log entry.

Orders can start asynchronous PDF invoice jobs, and administrators can upload product CSV files from the Products dashboard. The app-wide notification panel watches active jobs and shows a toast plus an unread notification when an invoice or CSV import succeeds or fails. The Background jobs page displays progress and row-level import errors, and downloads completed invoices. The storefront search combines partial-word, full-text, and typo-tolerant matching automatically and offers matching product suggestions while typing. CSV imports may include an optional `image_url` column; otherwise product images use name-based category matches.

Administrators process orders in separate status groups and can only advance an order through Pending, Packed, Shipped, Out for Delivery, Delivered, and Completed in sequence. Each order status notification is sent to that order's customer. Notifications and support conversations have separate controls and panels.

The admin Products section uses responsive product cards with in-place editing. Product images can be set with a validated HTTP(S) image URL and preview, or uploaded as a JPG, PNG, or WEBP file up to 5 MB; either option is available during create and edit.

Run the automated suites from this directory:

```sh
npm run typecheck
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Vitest uses React Testing Library and MSW for behavior-focused component tests, API contract handling, validation, and store coverage. Playwright's mocked browser suite verifies the frontend journeys, while the root GitHub Actions workflow separately runs these frontend checks and the FastAPI test suite on pushes and pull requests. To exercise the frontend against FastAPI locally, run the backend and its PostgreSQL/Redis dependencies as described in `../ecommerce-backend/README.md`, apply its Alembic migrations, then start Vite; the Vite `/api` proxy forwards requests to the configured `API_PROXY_TARGET`.

## Build And Audit

```sh
npm run lint
npm run build
npm run preview
```

In another terminal, audit the production preview (Vite's default preview URL is `http://localhost:4173/`):

```sh
npx lighthouse http://localhost:4173/ --only-categories=performance --output=html --output-path=./lighthouse-report.html
```

Route pages build as separate chunks. Lighthouse scores depend on browser/device emulation, network, API availability, and image-host response; 90+ is a measured target, not a guaranteed score. Do not use the Vite development server (`npm run dev`) for the score target because its unbundled modules and HMR skew performance results.

## AI shopping assistant

A floating **Ask AI** button appears at the bottom-right of the storefront for guests and signed-in shoppers. It opens a catalogue assistant with streamed responses and links to cited products. This is intentionally separate from **Live support** in the header, which remains the authenticated, human-operated WebSocket chat. The browser sends questions to the backend's `POST /ai/chat/stream` SSE endpoint; configure provider keys only in the backend `.env`, never in frontend `VITE_*` settings. Provider setup, fallback order, rate limit, and vector-index behavior are documented in `../ecommerce-backend/README.md`.