# shared (`shopease-shared`)

Small, stable infrastructure reused by every ShopEase component (ADR-14):

| Module | Provides |
|--------|----------|
| `settings.py` | `BaseServiceSettings`: `APP_ENV`, `LOG_LEVEL`, `DOCS_ENABLED` |
| `log_config.py` | JSON log lines on stdout with `service` and `request_id` |
| `request_id.py` | `X-Request-ID` middleware (accepts a safe incoming ID or creates `req-<hex>`) and one access-log line per request |
| `errors.py` | The error envelope (`docs/rest_api_notes.md` §1.8), handlers for 404/422/500, `ShopEaseError`, `not_implemented()` |
| `health.py` | `GET /health` (liveness) and `GET /health/ready` (readiness checks supplied by the service) |
| `app.py` | `install_common(app)`: wires the middleware and error handlers |

Keep this package thin. Models, database sessions, business rules and clients for other
services belong to the service that owns them, not here.

Install for local development (done by `requirements-dev.txt`): `pip install -e ./shared`.
Docker images install it from the repository root build context.
