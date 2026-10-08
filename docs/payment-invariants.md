# Payment consistency reference

AI-assisted documentation prepared for publication through the connected `SasyakSubudhi` account. This reference describes the existing containerised implementation; it does not redistribute earlier commit authorship.

Implementation: [Orders API](../services/orders.py), [Payments API](../services/payments.py), and [shared models and instrumentation](../services/common.py). Reproduction commands are in the [runbook](runbook.md).

## Invariants and boundaries

| Invariant | Mechanism | Boundary |
|---|---|---|
| A payment key stores one original transaction result | Unique `key` index and atomic `$setOnInsert` upsert | Applies inside the Payments database, not across independent installations |
| Identical retries return the original result | Lookup/upsert with the same key and comparison of the original payload | Includes order ID, amount, currency, and outcome |
| A changed payload cannot reuse a key | Conflict response `409` | A fresh key is a different payment request |
| An ambiguous response does not imply a decline | Orders remains pending after exhausted temporary failures | A `failed` state comes from a valid simulated payment result |
| Concurrent settlement does not overwrite terminal order state | Conditional order update filtered by `status: pending` | There is no distributed transaction spanning the two databases |
| Recovery survives an Orders restart | Persist the request and payment key before calling Payments | Requires the MongoDB data volume to remain intact |

## Failure matrix

| Event | Expected state and recovery |
|---|---|
| Successful simulated payment | Payment stores `paid`; Orders records that transaction ID and final state. |
| Declined simulated payment | Payment returns HTTP `200` with business status `failed`; Orders records failure. |
| Payment commits but the response times out | Orders may remain pending; subsequent settlement reuses the original key and returns the committed transaction. |
| Payments returns `429`, `502`, `503`, or `504` | Treat as temporary and retry within the configured attempt budget. |
| Request/response transport failure | Retry with the same key and payload; after exhaustion schedule pending recovery. |
| Permanent payment HTTP error below `500`, except `429` | Leave pending, record `permanent_payment_error`, and schedule a later attempt for investigation. |
| MongoDB is unavailable | Readiness fails. Database exceptions may fail requests or startup; recovery resumes when the dependency returns. |
| MongoDB volume is deleted or data is lost | These recovery guarantees do not recreate missing records. Use durable production storage and backups. |

Orders defaults to three attempts with a two-second operation timeout and a one-second connection timeout. Inter-attempt delays are `0.1 * 2**attempt` seconds. The recovery worker defaults to a five-second interval, scans up to 100 due records ordered by `next_attempt_at`, and reschedules unresolved records. Configuration can change these defaults.

## What to inspect during a timeout drill

1. Enable Payments' development response delay using the runbook. The delay happens after the payment record is persisted.
2. Create one order and retain its ID. A timeout is an uncertain response, not proof of payment failure.
3. Restore the normal delay and let recovery run. Retrieve the order until its final state is available.
4. Query the Payments ledger using `key: order:<order_id>`. Confirm one transaction record, then compare its transaction ID with the order.
5. Check structured `payment_retry` or `recovery_error` events and dependency readiness. Request metrics measure HTTP results; a business decline remains HTTP `200`.

Liveness checks the service process independently of MongoDB. Payments readiness requires MongoDB; Orders readiness requires MongoDB and Payments readiness. This prevents an unavailable dependency from being confused with a process-health signal.

## Production implications

This atomic simulation has no external payment side effect. A real provider needs provider-side idempotency, a durable processing state machine, reconciliation or webhooks, and an outbox or another reliable delivery mechanism. A new order submission remains a new order: the current Orders endpoint does not accept a client idempotency key. Permanent failures also need operator tooling and alerts rather than indefinite unattended retries.
