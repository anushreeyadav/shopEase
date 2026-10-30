# Day 1 Progress Report — ShopEase

**Date:** 2026-10-29
**Focus:** Research, technical documentation, API design, architecture diagrams (documentation only)
**Status at end of Day 1:** all Day 1 documentation delivered and validated. **No application
code was written on Day 1.** See [day1_handover_checklist.md](day1_handover_checklist.md).

## Completed Tasks

- [x] Inspected the existing workspace before making changes
- [x] Checked Git state: no repository is initialized. Git was not initialized, and nothing was committed or pushed.
- [x] Wrote the project overview, scope, stack, timeline and documentation index ([README.md](README.md))
- [x] Wrote an architecture overview with a text diagram ([architecture.md](architecture.md)); later updated to MySQL as a one-page summary
- [x] Compared monolithic and microservices architectures ([monolithic_vs_microservices.md](monolithic_vs_microservices.md)), with 8 trainee review questions
- [x] Defined service responsibilities, boundaries, a dependency graph, an ownership matrix and dev ports ([service_responsibilities.md](service_responsibilities.md))
- [x] Designed the database ownership model with table lists and a Mermaid diagram ([database_ownership.md](database_ownership.md), [database_ownership.mmd](database_ownership.mmd))
- [x] Wrote the REST API design and HTTP reference with endpoint contracts and sample JSON ([rest_api_notes.md](rest_api_notes.md))
- [x] Documented service communication and the checkout workflow, with a sequence diagram ([service_communication.md](service_communication.md), [checkout_sequence.mmd](checkout_sequence.mmd))
- [x] Produced the complete system architecture with a diagram and legend ([shopease_architecture.md](shopease_architecture.md), [shopease_architecture.mmd](shopease_architecture.mmd))
- [x] Recorded architecture decisions and open questions: ADR-01 to ADR-13, OPEN-01 to OPEN-14 ([implementation_decisions.md](implementation_decisions.md))
- [x] Performed the documentation review: diagrams parsed, cross-document consistency checked, inconsistencies fixed (see *Validation Results*)
- [x] Created the Day 2 handover checklist ([day1_handover_checklist.md](day1_handover_checklist.md))

## Topics Learned

- **Monolith vs. microservices:** what you gain (independent deployment and scaling, fault
  isolation) and what you pay (network failures, distributed data, more infrastructure).
- **Service decomposition:** splitting services by business domain, not by technical layer.
- **Database per service:** reference other services' data by ID, copy data at write time
  (price snapshots), and accept eventual consistency.
- **Sagas:** multi-service operations run as a series of local transactions, with
  compensating actions if a later step fails.
- **REST design:** naming resources, HTTP method meanings, status codes, a consistent
  error format, pagination and versioning.
- **Sync vs. async communication:** when to use REST calls and when to use events;
  timeouts, retries and circuit breakers.
- **API gateway pattern:** a single entry point that handles routing, edge authentication
  and rate limiting.
- **JWT:** stateless tokens issued by one service and verified locally by the others.
- **Authentication vs. authorization:** a valid token proves identity; roles and ownership
  checks live in the owning service.
- **Logical vs. physical database separation:** database-per-service is an ownership rule,
  enforced with per-service MySQL users, and doesn't require separate servers.
- **Idempotency:** idempotency keys prevent duplicate orders and duplicate charges when
  clients retry.
- **Uncertain outcomes:** a payment timeout is an *unknown* result to reconcile, never a
  reason to charge again.
- **Deadline budgets and bounded retries:** inner timeouts must fit inside outer ones;
  retries happen at one layer only and are always capped.
- **Correlation IDs and structured logs** for following one request across services.
- **Avoiding cyclic dependencies** between services (lazy profile creation, results pushed
  in one direction).

## Documents Prepared

| File | Status |
|------|--------|
| docs/README.md | Created; index updated during the review |
| docs/day1_progress.md | Created; updated at end of Day 1 |
| docs/implementation_decisions.md | Created; ADR-08 to ADR-13 and OPEN-12 to OPEN-14 added during the day |
| docs/architecture.md | Existed (PostgreSQL); updated to MySQL as a one-page summary during the review |
| docs/monolithic_vs_microservices.md | Existed as a short draft; replaced with the full comparison |
| docs/service_responsibilities.md | Existed as a short draft; replaced with the full specification; aligned with ADR-12/ADR-13 during the review |
| docs/database_ownership.md | Existed as a short draft; replaced with the full ownership model |
| docs/database_ownership.mmd | Created |
| docs/rest_api_notes.md | Existed as a short draft; replaced with the full REST reference |
| docs/service_communication.md | Existed as a short draft; replaced with the full communication and checkout document |
| docs/checkout_sequence.mmd | Created |
| docs/shopease_architecture.md | Created |
| docs/shopease_architecture.mmd | Created |
| docs/day1_handover_checklist.md | Created |

## Validation Results (performed during the end-of-day review)

Tools: Mermaid 11.4.1 parser (Node.js, installed in a temporary folder outside the project)
and Python consistency scripts. All checks were run against the final files.

| Check | Result |
|-------|--------|
| Mermaid diagrams parse (3 `.mmd` files + 3 embedded copies) | **6 / 6 pass** |
| Embedded diagram copies identical to their `.mmd` sources | **3 / 3 pass** |
| Architecture diagram: each of the 5 databases has exactly one solid ownership line from its owner; gateway has no database; all 15 network arrows labelled; legend present; provider marked as mock; JWT and coordination paths shown; no cycles | **Pass** |
| Checkout sequence: no circular calls; every one of 20 service/provider calls has a timeout; the only loop is capped (6 checks); all 12 state transitions valid; all 4 alternative flows present | **Pass** |
| Endpoints mentioned in every doc exist in the REST contract (41 canonical endpoints) | **Pass** |
| Named path placeholders, `/api` prefix, service/database names, port-to-component mapping, table names (16 = 16), local links, ADR/OPEN references (27 defined) | **Pass** |
| Stale terms (PostgreSQL in docs, `PAYMENT_FAILED`, old payment endpoints and scopes, old table/schema names) | **None found** (outside the decision log and this report, which keep history) |

**Re-verification (2026-10-29, later session):** the checks were run again on the final
files with a fresh Mermaid 11.4.1 install (outside the project). All 6 diagrams parse, and a
deliberately broken diagram fails as a negative control. All 3 embedded copies match their
`.mmd` sources. Every endpoint in the architecture, communication, ownership and handover docs
appears in rest_api_notes.md. Port mappings 8000–8005 are consistent, there are no broken
local links, and no stale PostgreSQL or `PAYMENT_FAILED` references remain in the design docs.
No fixes were needed.

## Issues and Solutions

| Issue | Solution |
|-------|----------|
| The workspace already contains a code scaffold (FastAPI stubs, Dockerfiles, gateway proxy, `docker-compose.yml`, a health test). It was generated before the Day 1 documentation-only rule was given. | Kept as instructed, with nothing added to it. Logged as OPEN-01 so the team decides what to do with it before Day 2. |
| The scaffold and `architecture.md` used PostgreSQL, but the target stack is MySQL. | Docs: fixed during the review (`architecture.md` now says MySQL). Scaffold files: still PostgreSQL, deferred to Day 2 (OPEN-11). |
| No Git repository exists. | Left alone; per the instructions, Git is not initialized without a request. |
| The required route `POST /api/payments` conflicted with ADR-10 (only order_service starts payments). | Two-step checkout recommended and recorded as **ADR-13**, **accepted by the project owner on 2026-10-29**; ADR-10 marked superseded; all docs aligned to ADR-13. |
| The documents drifted from each other as later tasks refined the design (paths without `/api`, `{id}` placeholders, `PAYMENT_FAILED` state, old table names, reversed order↔payment call). | Found with the consistency scripts and fixed in service_responsibilities, database_ownership (+ diagram), rest_api_notes, monolithic_vs_microservices, implementation_decisions, checkout_sequence and service_communication. |
| A review edit accidentally removed rows from the README documentation index (a line-ending mismatch in a scripted edit). | Detected while checking the README, restored manually, and line endings normalized (LF) across all docs. |

## Pending Work

- [x] ~~Confirm ADR-13 (two-step checkout)~~ (accepted 2026-10-29)
- [ ] Resolve the remaining open questions (OPEN-01 to OPEN-12, OPEN-14) in [implementation_decisions.md](implementation_decisions.md); blocking items are listed in the handover checklist
- [ ] Day 2: decide what to do with the existing code scaffold (OPEN-01, deferred)
- [ ] Day 2: replace PostgreSQL with MySQL in the scaffold files `docker-compose.yml` and `.env.example` (OPEN-11; the docs are done)
- [x] ~~Write detailed request/response schemas for each planned endpoint~~ (done in rest_api_notes.md for the representative routes; the remaining admin routes are listed with status codes)
- [ ] Draw full entity-relationship diagrams per service (table and key columns are in database_ownership.md)
- [x] ~~Add a sequence diagram for the order → payment → stock flow~~ (done: checkout_sequence.mmd)
- [ ] Plan the Postman collection layout (Day 2, step 9 of the handover order)
- [ ] Initialize the Git repository and push it to GitHub (only when instructed)
- [ ] Day 2: implementation, following [day1_handover_checklist.md](day1_handover_checklist.md)
