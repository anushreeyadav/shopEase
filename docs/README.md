# ShopEase Documentation

ShopEase is a microservices-based e-commerce management system.

## Objective

Design and build a backend for an e-commerce platform. It is split into independent
services for authentication, users, products, orders and payments, all reached through a
single API gateway. Each service owns its data and exposes a documented REST API.

## Scope

**In scope**
- User registration, login and JWT-based authentication
- User profile management
- Product catalog and inventory
- Order creation and order status tracking
- Payment recording (simulated; no real payment provider)
- An API gateway as the single entry point
- One MySQL database per service, with migrations
- Interactive API docs (Swagger UI) and a Postman collection
- Local orchestration with Docker Compose

**Out of scope**
- Frontend or UI
- Real payment gateway integration
- Production cloud deployment, Kubernetes, CI/CD pipelines
- Message broker / event-driven messaging (noted as a future option)

## Technology Stack

| Area | Technology |
|------|------------|
| Language | Python |
| Web framework | FastAPI |
| Database | MySQL |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Validation / schemas | Pydantic |
| Authentication | JWT |
| API style | REST |
| Containers | Docker, Docker Compose |
| API documentation | Swagger UI (FastAPI's built-in OpenAPI) |
| API testing | Postman |
| Version control | Git, GitHub |

## Timeline (Two-Day Deadline)

| Day | Focus | Rule |
|-----|-------|------|
| **Day 1** | Research, technical documentation, API design, architecture diagrams | Documentation only. No application code, business APIs, DB models, auth logic or Docker deployment. |
| **Day 2** | Implementation of the services described in these documents | Build against the Day 1 design |

## Deliverables

**Day 1**
- Architecture overview and diagram
- Monolithic vs. microservices comparison
- Service responsibilities
- Database ownership rules
- REST API design notes and planned endpoints
- Service communication approach
- Implementation decisions and open questions
- Day 1 progress report

**Day 2**
- Working FastAPI services backed by MySQL
- Alembic migrations per service
- JWT authentication
- Docker Compose setup
- Swagger UI for each service
- Postman collection

## Documentation Index

| Document | Contents |
|----------|----------|
| [final_architecture.md](final_architecture.md) | **Architecture as implemented** (diagram, Day 1 vs. built, limitations) |
| [api_reference.md](api_reference.md) | Every endpoint, generated from the OpenAPI schemas in [openapi/](openapi/) |
| [testing_report.md](testing_report.md) | Final test run: commands and actual results |
| [day2_progress.md](day2_progress.md) | Day 2 progress report |
| [submission_checklist.md](submission_checklist.md) | Final submission checklist |
| [shopease_architecture.md](shopease_architecture.md) | **Complete system architecture**: diagram, connections, JWT flow, coordination, isolation rules, ports, security boundaries, failure scenarios |
| [shopease_architecture.mmd](shopease_architecture.mmd) | Mermaid source of the system architecture diagram |
| [architecture.md](architecture.md) | One-page architecture summary and principles |
| [monolithic_vs_microservices.md](monolithic_vs_microservices.md) | Comparison of the two styles and why ShopEase uses microservices |
| [service_responsibilities.md](service_responsibilities.md) | What each service owns and does not do; dependency graph; ownership matrix; ports |
| [database_ownership.md](database_ownership.md) | Database-per-service rules and table ownership |
| [database_ownership.mmd](database_ownership.mmd) | Mermaid source of the database ownership diagram |
| [testing.md](testing.md) | Test layers and how to run them, coverage map, Postman collection, OpenAPI checks, latest results |
| [local_development.md](local_development.md) | Docker Compose stack: first start, startup order, isolation, migrations, mock payments, verification, restart limitations |
| [api_gateway.md](api_gateway.md) | Route map, what the gateway changes and hides, failure mapping, every public endpoint with its verification result |
| [order_workflow.md](order_workflow.md) | Checkout sequence, order status transitions, duplicate prevention, compensation, recovery, known gaps |
| [payment_processing.md](payment_processing.md) | Payment states, safety rules, **mock provider** behaviour, reconciliation, provider adapter boundary |
| [security_model.md](security_model.md) | Tokens, trust model, where authentication and authorization happen, known limitations |
| [database_setup.md](database_setup.md) | Creating the databases and users, running migrations, database tests |
| [rest_api_notes.md](rest_api_notes.md) | REST conventions, status codes, error format, endpoint contracts |
| [service_communication.md](service_communication.md) | Service-to-service calls, timeouts, retries, circuit breakers, idempotency, compensation, checkout workflow |
| [checkout_sequence.mmd](checkout_sequence.mmd) | Mermaid source of the checkout sequence diagram |
| [implementation_decisions.md](implementation_decisions.md) | Decisions made and questions still open |
| [day1_progress.md](day1_progress.md) | Day 1 progress report |
| [day1_handover_checklist.md](day1_handover_checklist.md) | Day 1 → Day 2 handover checklist and implementation order |

> **Note:** All documentation targets **MySQL**. The pre-Day-1 code scaffold was rewritten on
> Day 2 into service skeletons that also target MySQL (OPEN-01, OPEN-11 resolved; shared-code
> strategy in ADR-14). Run commands and ports are in the [root README](../README.md).
