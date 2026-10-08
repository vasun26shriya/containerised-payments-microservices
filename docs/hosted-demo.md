# Hosted demo and containerised project

AI-assisted documentation prepared for publication through the connected `yasho-26singh` account. Existing implementation commits retain their original authorship.

The public [Payments Lab dashboard](https://payments-live-app.vercel.app) lets a viewer try the core order/payment behavior without installing Docker. Its source lives in the separate [payments-live-app repository](https://github.com/vasun26shriya/payments-live-app).

## Choose the right demonstration

| Topic | Public Vercel app | This containerised repository |
|---|---|---|
| Order and payment simulation | Browser dashboard and `/api/*` routes | Separate Orders and Payments APIs |
| Persistent storage | MongoDB Atlas, browser-session scoped | Service-owned MongoDB databases |
| Duplicate payments | Unique `(session, key)` ledger index | Unique payment `key` ledger index |
| Failure recovery | Individual-order retrieval settles pending records | Orders background worker retries due pending orders |
| Runtime | One FastAPI application on Vercel | Independent Docker images and Kubernetes Deployments |
| Monitoring and release drills | Core application demonstration | Prometheus, Grafana, Alertmanager, Helm upgrades and rollback |

The public dashboard does not run this repository's Compose or Minikube stack. Both editions simulate payment outcomes and collect no card data.

## A browser walkthrough

1. Open the dashboard and check **API connected** and **MongoDB · persistent storage**.
2. Create an INR `42.00` order with the **Successful** outcome. Confirm **Paid** and the order/transaction identifiers. The stored API amount is `4200` minor units.
3. Retrieve the order. Refresh the browser page and use its history row to fetch the saved result again.
4. Create an INR `15.00` order with **Declined** selected. Confirm **Failed**. Business failure is a saved payment result.
5. Run **One key. One transaction.** Verify three concurrent responses share one transaction ID, then a changed amount returns `409 Conflict`.

Repeating **Create order** creates another order. The retry experiment demonstrates payment idempotency; it does not make order creation itself idempotent.

Public sandbox records are isolated by browser-session cookie and expire after seven days, subject to MongoDB TTL cleanup. A different browser can have an empty history. The 30-writes-per-minute session limit is a demo safeguard, not comprehensive abuse protection.

## Show the full engineering stack

For independent service deployment, timeout recovery, health probes, metrics, alerts, and Helm release drills, use the existing [deployment runbook](runbook.md), [local demo guide](demo-guide.md), and [verification record](verification.md). Keep the local API and monitoring endpoints on loopback unless using the documented secured configuration.

The [3:55 narrated video](https://github.com/vasun26shriya/payments-live-app/blob/main/docs/demo/Payments-Lab-Explained-and-Live-Demo.mp4) shows the hosted flow and explains the wider architecture. It uses synthetic narration and actual app captures with shortened pauses; it does not present the Kubernetes stack as hosted on Vercel.
