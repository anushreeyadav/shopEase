# Final Submission Checklist

Verified on 2026-10-30. Each item links to its evidence.

## Deliverables

- [x] Root `README.md`: overview, architecture, prerequisites, setup, environment, migrations,
      ports, Docker commands, API documentation URLs, testing, limitations
- [x] Final architecture and diagram: [final_architecture.md](final_architecture.md),
      [final_architecture.mmd](final_architecture.mmd) (diagram parses)
- [x] API reference: [api_reference.md](api_reference.md) generated from the services'
      OpenAPI schemas, exported to [openapi/](openapi/)
- [x] Database ownership with implemented tables and migration commands:
      [database_ownership.md](database_ownership.md) (generated section)
- [x] Testing report with commands and actual results: [testing_report.md](testing_report.md)
- [x] Day 2 progress report: [day2_progress.md](day2_progress.md)
- [x] Postman collection and sanitized environment template: `postman/` (no tokens, placeholders only)
- [x] Day 1 deliverables kept: [README.md](README.md) index, design documents, ADR log

## Implementation

- [x] Six components with `app/main.py` entry points (gateway + 5 services), each starting and healthy in Docker
- [x] Five databases, each accessed only by its owner (code audit + MySQL grant tests)
- [x] Migrations at head in every database (`auth_0001`, `user_0001`, `product_0002`, `order_0002`, `payment_0002`)
- [x] Authentication at the gateway and in every service; ownership checks inside services
- [x] Payment idempotency (unique key, one active payment per order, provider idempotency key)
- [x] Stock concurrency safeguards (row locks, checks, version column) proven on MySQL
- [x] Mock payment provider only; refused in production
- [x] Docker Compose: non-root images, health checks, startup order, isolated networks, localhost-only ports, MySQL unpublished

## Verification

- [x] Unit + API tests: 374 passed, 0 failed
- [x] MySQL integration tests: 65 passed, 0 failed
- [x] Cross-service integration tests: 54 passed, 0 failed
- [x] Postman via Newman: 38 requests, 122 assertions, 0 failed
- [x] `docker compose config` valid; images build; stack starts healthy; restarts verified
- [x] OpenAPI documents verified by tests (protected operations answer 401 without a token)

## Hygiene and Git

- [x] No `.env`, keys, tokens, virtual environments, caches, coverage files or database dumps committed
- [x] `.env.example` and Postman environment contain placeholders only
- [x] Secret scan of committed files: no real secrets (test placeholders reviewed)
- [x] Work committed in topic commits on `main`; history not rewritten
- [ ] Pushed to GitHub — **not done**: waiting for an explicit instruction and a remote

## Known gaps (documented, not hidden)

- [ ] Real payment provider and webhooks
- [ ] Stock return after refund of a paid order; manual-review tooling
- [ ] Token revocation list, shared rate-limit store, coordinated background jobs
- [ ] CI/CD, load testing, independent security review
