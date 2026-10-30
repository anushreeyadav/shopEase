# Architecture Overview

A one-page summary. The complete architecture, with the full diagram, connections, security
boundaries and failure scenarios, is in
**[shopease_architecture.md](shopease_architecture.md)**.

```
                    +----------------------+
  Client ---------> |  API Gateway  :8000  |   single entry point; no business database
                    +----------+-----------+
       +-----------+-----------+-----------+-----------+
       v           v           v           v           v
   auth:8001   user:8002  product:8003  order:8004  payment:8005 ---> payment provider (dev mock)
       |           |           |           |           |
   auth_db     user_db    product_db    order_db    payment_db     (one owner each, MySQL)

  Service-to-service REST:  order -> product, order -> user, payment -> order
  Every service fetches JWKS keys and service tokens from auth (cached).
```

## Principles

1. **One service, one business capability.** Services are split by domain, not by
   technical layer.
2. **Database per service.** Each service owns one logical MySQL database. No service reads
   another service's tables. See [database_ownership.md](database_ownership.md).
3. **Single entry point.** Clients only talk to the API Gateway, which routes, checks JWTs at
   the edge, limits rates and adds correlation IDs. It has no business logic.
4. **Independently deployable.** Each service has its own codebase, dependencies, migrations
   and container, and can be released alone.
5. **Stateless services.** State lives in the databases, so services can be scaled
   horizontally.
6. **Acyclic, authenticated service calls.** REST calls between services form a directed
   acyclic graph and always carry a service token (ADR-08, ADR-11).

## Technology stack

- Python, FastAPI, Pydantic, Uvicorn
- MySQL (one logical database per service), SQLAlchemy, Alembic
- JWT (RS256 proposed) for authentication
- httpx for service-to-service REST calls
- Docker and Docker Compose for local orchestration
- Swagger UI (FastAPI's built-in docs) and Postman for API testing
