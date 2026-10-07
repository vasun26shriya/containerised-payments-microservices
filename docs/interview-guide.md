# Explain the design

Start with: “I built independently containerised Orders and Payments APIs with durable MongoDB state, atomic payment idempotency, restart recovery, Helm release verification and observable deployments.”

## Questions and defensible answers

**How do you prevent duplicate payments?** A unique MongoDB key index and atomic `$setOnInsert` upsert store the original payload and final simulated result together. Concurrent losers read the winning record. Matching retries return its transaction ID; a changed payload returns 409. There is no real external provider, so this atomic simulation does not establish exactly-once charging in a real payment network.

**What if a payment commits but its response is lost?** Orders first persists a pending order and stable payment key. Every attempt uses that key. Timeouts leave the order pending, and a worker retries due records after restart. The recorded demo demonstrates this with actual HTTP timeouts. A declined payment is a final business outcome; a network error is ambiguous.

**Why separate databases?** Each service owns its data and credentials. Orders communicates through the Payments API rather than reading its transactions. The authenticated Compose demonstration proves each database user cannot read the other database. This avoids distributed transactions but means order state converges asynchronously.

**Are order submissions idempotent?** No. Creating two orders creates two records. Payment retries for an existing order are idempotent. Client order-creation idempotency would need its own key, payload fingerprint and durable result mapping.

**What do readiness and liveness mean?** Liveness says the process is running; readiness checks database availability. They remain accessible to internal probes even when business endpoints require authentication. Production ingress and network policy should restrict these operational endpoints.

**What does rollback guarantee?** Helm rolls back deployment configuration and images. It does not reverse payments or database changes. The drill checks a persisted order after upgrade and rollback. Real schema changes require backward-compatible migrations and an explicit recovery plan.

**How is access controlled?** Each API uses a separate machine bearer token with constant-time comparison. Orders holds the Payments token for its outbound call. File-mounted secrets keep credentials out of source and evidence. This is service authentication, not end-user identity, roles or granular authorization. TLS and a managed secret controller remain deployment-specific production work.

**How do you know it works?** Real MongoDB integration tests cover concurrent races; actual TCP tests lose responses and restart both services. CI also runs Compose and Kubernetes release checks, secured-stack checks, restore verification, and image scans before SHA-tag publication. Read the verification record for the exact validated revision.

**What would you change for real payments?** Provider idempotency, reconciliation and signed webhooks; a durable processing state machine/outbox; replica sets and majority writes; client authentication and authorization; TLS/network policy; worker leases, jitter, bounded concurrency, retry budgets and pending-age alerts. Offsite encrypted backups need retention and scheduled restore drills.

## Resume entry

Built a containerised payment simulation using FastAPI and MongoDB, with atomic idempotency and restart recovery; automated Compose and Minikube verification, Helm upgrade/rollback checks, Prometheus/Grafana monitoring, authenticated service access, backup restore drills and SHA-tag Docker image publication.

Use measured counts and outcomes from [verification](verification.md). Do not claim real money processing, production certification, a zero-vulnerability scan or unmeasured throughput.
