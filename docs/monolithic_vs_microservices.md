# Monolithic vs. Microservices Architecture

This document explains the two architectural styles, what each costs and gives you, and
how they would shape ShopEase. Neither style is better in general. The right choice
depends on team size, domain complexity, scaling needs and how much operational work the
team can take on.

---

## 1. Monolithic Architecture

### What it is

A monolith is a single application. All of its features (authentication, users, products,
orders, payments) are built, tested and **deployed together as one unit**. It usually runs
as one process (or several identical copies behind a load balancer) and normally uses one
shared database.

A monolith can still be well structured inside: separate modules, layers and packages. A
**modular monolith** keeps clear boundaries between modules but still ships as one
deployable.

### How a request is processed

```
Client
  |  HTTP request
  v
+--------------------------------------------------------------+
|                    ShopEase Monolith                          |
|                                                              |
|  Router -> Auth middleware -> Order module                   |
|                                 |  in-process function calls |
|                                 +-> Product module           |
|                                 +-> Payment module           |
|                                                              |
|  One database connection pool, one transaction if needed     |
+--------------------------------------------------------------+
  |
  v
Single MySQL database (all tables)
```

1. One HTTP request reaches the application.
2. Routing and middleware (for example, authentication) run inside the same process.
3. Modules call each other as **ordinary function calls**: fast, no network involved.
4. All the data changes can be wrapped in **one database transaction** (ACID).
5. One response is returned.

---

## 2. Microservices Architecture

### What it is

Microservices split the system into small services, each built around one **business
capability**. Each service:

- runs as its own process (often its own container),
- has its own codebase or build, dependencies and release cycle,
- **owns its data**, which other services reach only through its API,
- talks to other services over the network (HTTP/REST, gRPC or messages).

### Independently deployable services

The key property is **independent deployability**. A service can be built, tested,
released, rolled back and scaled **without redeploying or coordinating with any other
service**, as long as its API contract stays compatible.

> **Splitting code into folders is not microservices.** A repository with `services/auth/`
> and `services/orders/` folders that still compiles into one process, shares one database
> schema, or must be released together is still a monolith, just a modular one. Services
> that must always be deployed together and share tables are often called a **distributed
> monolith**: they have the costs of microservices and almost none of the benefits.

What independent deployment requires:

- **Separate runtime units**: each service runs and restarts on its own.
- **Stable, versioned API contracts**: changes are backward compatible, or versioned.
- **No shared database tables**: otherwise a schema change in one service can break another.
- **A separate build and release pipeline** for each service.

### How a request is processed

```
Client
  |  HTTPS
  v
+-------------+
| API Gateway |  routing, JWT check, rate limiting
+------+------+
       |  HTTP (network hop)
       v
+---------------+   HTTP    +-----------------+   HTTP   +-----------------+
| order_service |---------->| product_service |          | payment_service |
|               |-------------------------------------->|                 |
+-------+-------+           +--------+--------+          +--------+--------+
        |                            |                            |
   orders schema              products schema             payments schema
   (owned by order)           (owned by product)          (owned by payment)
```

1. The client calls the **API gateway**.
2. The gateway checks the token and forwards the request to the right service.
3. That service may call other services **over the network** to get data or trigger actions.
4. Each service writes only to **its own** data, in its own local transaction.
5. There is **no single transaction across services**. Keeping data consistent across
   services needs explicit patterns (see Section 4).

---

## 3. Advantages and Disadvantages

### Monolith

| Advantages | Disadvantages |
|-----------|---------------|
| Simple to develop, run and debug locally | Any change means rebuilding and redeploying the whole application |
| Fast in-process calls, no network latency between modules | Can only scale as a whole, even if just one feature is busy |
| One ACID transaction can cover many features | One faulty module (memory leak, crash) can take down everything |
| End-to-end testing is straightforward | The codebase tends to tangle as it grows, without discipline |
| Little infrastructure: one app, one database | Large teams step on each other; releases need coordination |
| Easy refactoring across modules (the IDE sees everything) | Locked into one technology stack |

### Microservices

| Advantages | Disadvantages |
|-----------|---------------|
| Deploy, roll back and release each service on its own | Distributed-system failure modes: timeouts, partial failures, retries, duplicate requests |
| Scale only the services that need it | Network latency on every service-to-service call |
| Failures can be contained to one service (with good design) | No cross-service ACID transactions; consistency is usually eventual |
| Teams can own services end to end | Much more operational work: CI/CD per service, monitoring, tracing, configuration, secrets |
| Smaller codebases are easier to understand on their own | End-to-end and integration testing is harder |
| Each service can choose its own tools if needed | Debugging a request across many services needs distributed tracing |
| | Changing an API contract needs versioning and coordination |

---

## 4. Key Concerns, Compared

### Scaling
- **Monolith:** scales **horizontally as a whole**: run more identical copies behind a load
  balancer. That works well, but you pay to copy features that don't need extra capacity.
  The shared database often becomes the bottleneck.
- **Microservices:** scale **each service separately**. For example, run many copies of
  product_service during a sale and keep payment_service small. This only helps if the
  service's own database and its dependencies can also handle the load.

### Deployment
- **Monolith:** one artifact and one pipeline. Simple, but every release ships everything,
  so one risky change holds up all the others.
- **Microservices:** many artifacts and pipelines. Releases are smaller and less risky, but
  you need automation, versioned contracts and good deployment practices (rolling updates,
  canary releases, rollback).

### Maintenance
- **Monolith:** everything is in one place, which is easy at first. Over time, unclear
  module boundaries make changes ripple unpredictably.
- **Microservices:** clear boundaries make each service easier to change. But the whole
  system has more parts to upgrade, patch and keep compatible: libraries, base images,
  API versions.

### Testing
- **Monolith:** unit and integration tests run in one process. End-to-end tests are simple
  to set up.
- **Microservices:** each service is easy to unit-test on its own. Integration needs
  **contract tests** (to check that services agree on their APIs) and an environment with
  several services running. Full end-to-end tests are slower and break more easily.

### Fault Isolation
- **Monolith:** an unhandled crash, memory leak or thread exhaustion in one module can
  bring down the whole process.
- **Microservices:** one failing service *can* be isolated. This **does not happen
  automatically**. Without timeouts, circuit breakers and fallbacks, a slow service makes
  its callers wait, and failures **cascade** through the system.

### Data Consistency
- **Monolith:** one database means one ACID transaction can update an order, stock and the
  payment together. Either everything commits or nothing does.
- **Microservices:** each service owns its data, so one operation that spans services is a
  series of **local transactions**. Consistency is usually **eventual**, coordinated by the
  **Saga pattern**: each step has a *compensating action* (refund the payment, release the
  stock) if a later step fails. Two-phase commit across services is generally avoided,
  because it couples services together and hurts availability.

### Database-per-service: logical ownership, not necessarily separate servers
"Database per service" is an **ownership rule**: only the owning service reads and writes
its data, and other services must go through its API. It **does not require** a separate
physical MySQL server for each service. Common options:

| Option | Isolation | Cost / effort |
|--------|-----------|---------------|
| Private tables in a shared schema | Weakest; relies on discipline | Lowest |
| **Separate schema per service on one MySQL server, each with its own DB user and privileges** | Good logical isolation | Low; a sensible default for ShopEase |
| Separate MySQL server or instance per service | Strongest; separate resources and failures | Highest |

On a shared server, services still compete for CPU, memory and connections, and an outage
of that server affects all of them. Teams usually accept that trade-off early on.

### Network Latency
- **Monolith:** module calls are in-memory and take nanoseconds to microseconds.
- **Microservices:** each call between services adds network time (usually milliseconds),
  serialization work and the risk of failure. A request that fans out to several services
  in sequence adds up those delays. **Microservices are not faster per request.** They
  are often slower, and their benefits lie elsewhere: scaling, independent change, team
  autonomy.

### Operational Complexity
- **Monolith:** one application to deploy, monitor and log.
- **Microservices:** you also need an API gateway, service discovery, centralized
  configuration and secrets, central logging, metrics, distributed tracing, a CI/CD
  pipeline per service, and often container orchestration. This overhead is real and is
  the main reason small teams should be careful about adopting microservices.

---

## 5. When Each Approach Fits

### Why microservices may suit a growing e-commerce enterprise
- **Uneven load:** product browsing and search get far more traffic than checkout, and
  traffic spikes during sales. Scaling only the catalog saves money.
- **Different change rates:** promotions and catalog features change weekly, while payment
  code changes rarely and carefully.
- **Isolation of sensitive areas:** payments benefit from a smaller attack surface and
  stricter access control.
- **Team growth:** several teams can each own a domain (catalog, orders, payments) and
  release on their own schedules.
- **Resilience goals:** if recommendations or reviews go down, customers should still be
  able to check out.

### When a monolith might be preferable
- A small team, or an early-stage product whose domain boundaries are still changing.
  Splitting too early tends to draw the boundaries in the wrong places.
- No strong need for independent scaling.
- No mature DevOps, monitoring or CI/CD skills yet.
- Strong consistency matters more than scaling each part separately.
- Tight deadlines, where infrastructure work would slow down feature delivery.

A common, practical path is to **start with a well-structured modular monolith** and pull
out services when there is a concrete reason, such as a scaling, team or isolation need.

> **ShopEase note:** ShopEase uses microservices mainly as a **learning objective** and to
> show the pattern. With a two-day timeline and a small team, a modular monolith would be
> the more practical choice in a real business setting.

---

## 6. Comparison Table

| Aspect | Monolith | Microservices |
|--------|----------|---------------|
| **Deployment** | One artifact; every release ships everything | Each service deployed and rolled back on its own |
| **Scalability** | Scale the whole application; the shared DB is often the bottleneck | Scale each service separately, by its own load |
| **Database design** | One shared database; cross-feature joins and ACID transactions | Database per service (logical ownership); no cross-service joins; eventual consistency through sagas |
| **Team ownership** | Shared codebase; teams split by layer or feature, releases coordinated | A team owns a service end to end (code, data, deployment) |
| **Reliability** | One process failure can affect everything; fewer moving parts | Failures can be contained with timeouts and circuit breakers; but more parts can fail, and failures can cascade |
| **Complexity** | Complexity lives **in the code** | Complexity moves **into the infrastructure and the network** |
| **Performance per request** | In-process calls; low latency | Network hops add latency and failure risk |
| **Testing** | Simple end-to-end testing | Easy unit tests; needs contract and integration testing |
| **Technology choice** | One stack | Can differ per service (usually standardized anyway) |

---

## 7. ShopEase Example

### Product browsing (`GET /api/products?category_id=...`)

| | Monolith | Microservices |
|-|----------|---------------|
| Flow | Request → product module → `SELECT` from the shared database → response | Client → gateway → product_service → products schema → response |
| Scaling | During a sale, the whole application is scaled up | Only product_service gets more copies |
| Failure impact | An unrelated bug elsewhere (say, in payments) can crash the process and stop browsing | If payment_service is down, browsing still works |
| Latency | Lowest | One extra hop through the gateway |

### Order creation (`POST /api/orders`)

**Monolith**
```
BEGIN TRANSACTION
  check product prices and stock      (product module, in-process)
  insert order + order_items          (order module)
  decrement stock                     (product module)
COMMIT  -- all changes happen, or none
```

**Microservices**
```
order_service -> GET product_service /products/{id}    (network call: prices, stock)
order_service: insert order (status = PENDING)       (local transaction in the orders schema)
order_service -> POST product_service /reservations     (network call: reserve stock)
```
- order_service **cannot join** onto the products tables. It must ask product_service.
- It stores a **price snapshot** in `order_items` so later catalog changes don't alter the order.
- If the reservation call times out, order_service must decide whether to retry or cancel.
  Retries must be **idempotent**, so stock is not reserved twice.

### Payment processing (during checkout)

**Monolith**
- The payment module charges the customer and updates the order status inside one
  transaction or one code path. If the charge fails, the transaction rolls back.

**Microservices** (saga, two-step checkout per ADR-13)
```
1. order_service      creates order, reserves stock    -> AWAITING_PAYMENT
2. client             POST /api/payments
   payment_service    gets the payable amount from order_service, charges -> SUCCEEDED / FAILED
3a. on SUCCEEDED:     order_service confirms the stock deduction, order -> PAID
3b. on FAILED:        order stays AWAITING_PAYMENT (customer may retry);
                      if never paid, it expires -> CANCELLED and stock is released
4. if confirming stock fails after payment succeeded:
                      order -> CANCELLED, payment_service issues a refund (compensating action)
```
- Between steps, the system is **temporarily inconsistent**. For example, the order is
  PENDING while the payment is in progress. The UI and business rules must handle this.
- payment_service can be locked down separately (network rules, secrets, audit logging)
  and released less often.

---

## 8. Supporting Infrastructure for Microservices

### API Gateway
A single entry point for clients. It routes requests to services, checks JWTs at the edge,
and handles rate limiting, CORS and TLS termination. It can also combine responses from
several services. It hides the internal service layout from clients. The gateway must be
highly available, because it is on every request path, and it should not contain
business logic.

### Observability
With requests crossing many services, you can't debug by reading one log file.
Observability rests on three pillars:
- **Centralized logs**: structured logs from every service, gathered in one searchable
  place, each tagged with a **correlation/request ID** that the gateway passes along.
- **Metrics**: request rate, error rate and latency (p95/p99) per service, plus saturation;
  dashboards and alerts are built on these.
- **Distributed tracing**: follows a single request across services (for example with
  OpenTelemetry) to show where time was spent and where it failed.

### Service Discovery
Service copies come and go as they scale and restart, so their addresses change. Service
discovery lets one service find another by **name** instead of a fixed IP. Options include
Docker Compose's built-in DNS (the service name is the hostname), Kubernetes Services, or
a registry such as Consul. Discovery is usually paired with load balancing across healthy
copies, based on health checks.

### Centralized Configuration
Each service needs settings: database URLs, other services' URLs, JWT settings, feature
flags. Centralized configuration keeps these **outside the code** (environment variables,
config files or a config server) and keeps **secrets** in a secure store, never in Git.
Configuration should differ per environment (dev/test/prod) without rebuilding the image,
so the same artifact runs everywhere.

---

## Conclusion

A monolith keeps complexity inside one codebase. It is simpler to build, test and run, and
it guarantees strong consistency through a single database. Microservices move complexity
into the network and the infrastructure. In return you get independent deployment,
per-service scaling, team autonomy and the *possibility* of failure isolation. The price
is distributed-system failure modes, eventual consistency, extra latency and significant
operational overhead.

Microservices are not automatically better or faster. They pay off when there is a real
need for independent scaling, deployment or ownership. ShopEase adopts them to learn and
demonstrate these patterns. The design applies the principles that make the style work:
clear service boundaries, logical database ownership, versioned APIs, a gateway, and
observability.

---

## Review Questions for Trainees

**1. What makes a service "independently deployable", and why isn't splitting code into
folders enough?**
A service is independently deployable if it can be built, released, rolled back and scaled
without redeploying any other service. That requires a separate runtime, a stable API
contract and no shared database tables. Folders inside one deployable are still a
monolith. Separate services that share tables or must be released together form a
distributed monolith.

**2. Are microservices faster than a monolith?**
Not per request. Calls between services add network latency, serialization work and
failure risk, which in-process calls don't have. The benefits are elsewhere: scaling
selected parts, deploying independently, isolating faults and letting teams work on their
own.

**3. How is data consistency kept when placing an order across order, product and payment
services?**
There is no single cross-service ACID transaction. The flow is a saga: a series of local
transactions, each with a compensating action (release stock, refund payment) if a later
step fails. Consistency is eventual, so the system must handle intermediate states like
PENDING. Retries must be idempotent.

**4. Does "database per service" mean every service needs its own MySQL server?**
No. It is a logical ownership rule: only the owning service accesses its data, and others
go through its API. It can be done with a separate schema and DB user per service on one
MySQL server. Separate servers give stronger resource and failure isolation, at higher
cost.

**5. If payment_service becomes slow, how could that affect the rest of the system, and how
do you prevent it?**
Callers waiting on it can run out of threads or connections and start failing too: a
cascading failure. Prevent this with timeouts, circuit breakers, limited retries with
backoff, bulkheads (separate resource pools per dependency), and asynchronous processing
where possible.

**6. When would you recommend a monolith over microservices?**
For a small team, an early-stage product whose domain boundaries are still unclear, a
system without strong independent-scaling needs, a team without mature DevOps and
monitoring, or a case where strong consistency matters most. A modular monolith keeps the
option of extracting services later.

**7. What does an API gateway do, and what shouldn't it do?**
It is the single client entry point: routing, edge authentication, rate limiting, CORS, TLS
and sometimes response combining. It should not contain business logic. It must be highly
available, since every request passes through it.

**8. Why is distributed tracing needed in microservices but rarely in a monolith?**
In a monolith, one request runs inside one process and one stack trace. In microservices,
one request crosses several services and networks. Tracing with a shared correlation ID
rebuilds the full path and shows where the time went and where the failure happened.
