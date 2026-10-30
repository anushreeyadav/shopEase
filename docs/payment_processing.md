# Payment Processing

How payment_service records payments, talks to a payment provider, and stays safe when the
outcome of a charge is unknown. Implemented 2026-10-30. Code: `services/payment_service/app/`
(`payments.py` rules, `providers/` adapter boundary and mock, `clients.py` calls to
order_service).

> ## ⚠ MOCK PROVIDER ONLY
> The only provider implemented is **`MockProvider`**, a **simulation for local development
> and automated tests**. It **moves no money**, contacts **no** bank, card network or payment
> company, and runs entirely inside the payment_service process. Every "charge" is an entry
> in an in-memory dictionary. Its references start with `mock_` (`mock_txn_…`, `mock_rfnd_…`)
> and its card brand is `MOCKVISA`, so its records can't be mistaken for real ones.
> **payment_service refuses to start with the mock when `APP_ENV=production`.** Connecting a
> real payment gateway is future work behind the adapter boundary in §6.

Related: ADR-13 (two-step checkout), ADR-19 (this design) in
[implementation_decisions.md](implementation_decisions.md) · [order_workflow.md](order_workflow.md)
· contracts in [rest_api_notes.md](rest_api_notes.md) §3.6.

---

## 1. Flow

1. The customer creates an order (order_service), then calls `POST /api/payments` with the
   `order_id`, a **payment-method token** and an `Idempotency-Key`.
2. payment_service asks order_service for the **payable view** (amount, currency, owner,
   whether it can be paid). The amount is **never** taken from the client. If the client
   sends `expected_amount`/`currency`, they must match exactly (`409 AMOUNT_MISMATCH` /
   `CURRENCY_MISMATCH`, nothing charged).
3. The payment is recorded as `INITIATED`, holding the order's single **active payment** slot.
4. The provider is called with **our payment ID as its idempotency key**. No database
   transaction is open during the call.
5. The outcome is stored, then **reported to order_service** (`payment-result`), which
   confirms the stock and sets the order `PAID`, or keeps it `AWAITING_PAYMENT` after a
   decline. If the order can no longer accept the money, payment_service **refunds** it.

## 2. Payment states

| Stored status | Meaning | Equivalent in the task's terms |
|---------------|---------|--------------------------------|
| `INITIATED` | Recorded; provider not yet answered | **PENDING** |
| `PROCESSING` | Outcome **unknown** (timeout, provider still processing, or an inconsistent answer). Reconciliation required | **REQUIRES_RECONCILIATION** |
| `PROCESSING` + `requires_review: true` | Automatic reconciliation stopped (schedule exhausted, provider amount mismatch, duplicate provider reference). A person must resolve it | REQUIRES_RECONCILIATION (manual) |
| `SUCCEEDED` | The provider **accepted** the charge and amount, currency and reference checked out | SUCCEEDED |
| `FAILED` | Declined, provider unreachable before sending, or the provider has no record of it | FAILED |
| `REFUNDED` | Fully refunded (partial refunds keep `SUCCEEDED` and list the refunds) | — |

The names come from the approved schema (`payment_0001`) and order_service already uses
`PROCESSING`; the mapping above is the only difference from the task's examples.

```
None ──► INITIATED ──► SUCCEEDED ──► REFUNDED
             │    └──► FAILED
             └──► PROCESSING ──► SUCCEEDED / FAILED     (reconciliation)
```

Every change appends `payment_status_history` (from, to, source `API` or `RECONCILIATION`,
time). `GET /api/payments/{payment_id}` shows it as the transaction history.

## 3. Safety rules

| Rule | How it is enforced |
|------|--------------------|
| No card data | The API accepts only an opaque `payment_method_token`. Tokens containing 12+ consecutive digits are rejected (`422`, input not echoed). The token is never stored or logged (only a SHA-256 inside the request fingerprint). Stored: brand, last four, provider reference |
| Success only on an accepted provider result | `SUCCEEDED` is set only when the provider returns an accepted charge **and** its amount and currency equal ours **and** its reference is not already recorded (`UNIQUE(provider, provider_txn_ref)`). Otherwise the payment stays `PROCESSING` with `requires_review` |
| Timeouts are unknown outcomes | `ProviderTimeout` → `PROCESSING`, `202 Accepted`. Reconciled with `get_status` on 30s, 2m, 10m, 1h, 6h, 24h; then manual review. **The charge is never sent again** |
| No blind retries | `charge` and `refund` are called once per request. Only reads (`payable`) are retried inline. Result reports to order_service are retried by the background job, which is safe because order_service applies them idempotently |
| No duplicate charges | `Idempotency-Key` is unique in `payment_db` (same key + same request → the stored result; different request → `409 IDEMPOTENCY_KEY_REUSED`, nothing leaked). `active_order_id` is unique: a second payment while one is `INITIATED`/`PROCESSING`/`SUCCEEDED` → `409 PAYMENT_ALREADY_IN_PROGRESS`. The provider receives our payment ID as its idempotency key |
| Only the owner pays | The payable view's `user_id` must equal the token's `sub`; otherwise `404` (no ID probing). Reads: owner or admin. Refunds: admin. Reconciliation endpoint: service token with scope `payments:reconcile` |
| Nothing charged when dependencies are down | order_service unavailable → `503`/`504` before any charge. Provider unreachable before sending → `FAILED (provider_unavailable)`, `503` |
| Safe errors | Standard envelope; no tokens, card data, provider secrets or stack traces |

## 4. Mock provider behaviour (development and tests only)

Choose the simulated behaviour with the payment-method token. Any other token is rejected
with `422 INVALID_PAYMENT_METHOD`.

| Token | Simulated behaviour | API result |
|-------|---------------------|------------|
| `mock_tok_success` | Accepted | `201 SUCCEEDED` |
| `mock_tok_decline` | Declined (`card_declined`) | `422 PAYMENT_DECLINED` |
| `mock_tok_insufficient_funds` | Declined (`insufficient_funds`) | `422 PAYMENT_DECLINED` |
| `mock_tok_timeout` | Accepted, response lost | `202 PROCESSING` → reconciled to `SUCCEEDED` |
| `mock_tok_timeout_declined` | Declined, response lost | `202 PROCESSING` → reconciled to `FAILED` |
| `mock_tok_pending` | Still processing | `202 PROCESSING` → manual review after the schedule |
| `mock_tok_unavailable` | Unreachable before sending | `503 PAYMENT_PROVIDER_UNAVAILABLE`, nothing charged |
| `mock_tok_duplicate_ref` | Accepted with the fixed reference `mock_txn_duplicate` | first `201`; any later one `202 PROCESSING` + review |
| `mock_tok_amount_mismatch` | Accepted for 1.00 more than requested | `202 PROCESSING` + review, never `SUCCEEDED` |

Mock specifics: charges are idempotent per key, like a real provider. State is **in memory**:
after a restart `get_status` knows nothing and payment_service records `FAILED
(not_found_at_provider)`. That interpretation is valid **only for the mock**; a real adapter
must decide from the provider's documented semantics. Mock refunds always succeed.

## 5. Order coordination and compensation

| Situation | What payment_service does |
|-----------|---------------------------|
| Order not payable (paid, cancelled, expired) | `409 ORDER_NOT_PAYABLE`, nothing charged |
| Charge succeeded, order_service answers `409 ORDER_NOT_FULFILLABLE` / `ORDER_ALREADY_PAID` | Automatic full refund (idempotency key `auto-{payment_id}`), status `REFUNDED`, reported; the client gets `409 ORDER_NOT_FULFILLABLE` |
| Result report fails (order_service down) | The payment keeps its status; the background job retries with backoff (up to `MAX_REPORT_ATTEMPTS`, then manual review). The client already got `201` |
| Admin refund | `POST /api/payments/{id}/refunds` (full or partial, `Idempotency-Key`); a full refund sets `REFUNDED` and is reported, and order_service cancels a `PAID` order |
| Process stops between recording and charging | A payment `INITIATED` for over a minute is reconciled like an unknown outcome |

## 6. Provider adapter boundary

`app/providers/base.py` defines `PaymentProvider`: `validate_token`, `charge`, `get_status`,
`refund`, plus three exceptions. A real adapter must:

- send our payment/refund ID as the provider's **idempotency key**;
- raise `ProviderUnavailable` **only** when the request certainly never reached the provider,
  and `ProviderTimeout` whenever it might have been processed;
- return amount, currency and reference so payment_service can verify them;
- accept only provider-issued tokens (card data is collected and tokenized by the provider's
  client-side SDK; ShopEase never sees it);
- read API keys from secret configuration, never from code;
- verify webhook signatures in `POST /api/payments/webhooks/{provider}` (currently `501`:
  the mock sends no webhooks).

Selection: `PAYMENT_PROVIDER=mock` (the only value). Adding a provider means a new class in
`app/providers/` and a branch in `build_provider`.

## 7. Known gaps

| Gap | Current behaviour |
|-----|-------------------|
| No real provider | Mock only; production start is refused |
| Webhooks | Route returns `501`; reconciliation is the only status source |
| Refund outcome unknown (provider error during refund) | Refund `PROCESSING` and the payment flagged `requires_review`; no automatic refund reconciliation |
| Stock after refund of a paid order | Not returned automatically (see [order_workflow.md](order_workflow.md) §6) |
| ~~Gateway timeout~~ | Resolved: payments have their own 20s gateway timeout (`PAYMENT_UPSTREAM_TIMEOUT_SECONDS`) |
| Manual-review tooling | Flagged payments are visible (`requires_review`, ERROR log); there is no admin resolution endpoint yet |
| Background job | Runs in every payment_service instance; actions are idempotent, but not coordinated |
