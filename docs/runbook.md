# Deployment and operations runbook

Commands below use PowerShell at repository root. Install Docker Desktop (Linux containers), Python 3.13, Helm 3.17+, kubectl and Minikube. Allocate at least four CPUs and 6 GiB RAM for a full cluster. Local stack endpoints bind loopback; do not expose unauthenticated demo services publicly.

## Compose and monitoring

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail 100 orders payments
```

Orders: http://localhost:8000/docs; Payments: http://localhost:8001/docs. Prometheus http://localhost:9090, Grafana http://localhost:3000 (admin / configured `GRAFANA_ADMIN_PASSWORD`), Alertmanager http://localhost:9093. Grafana automatically provisions the Payments Microservices dashboard and Prometheus datasource. Prometheus Targets must show both APIs UP. Request count, latency buckets and status labels appear after traffic. Alertmanager receives alerts but has no notification integration until its placeholder receiver is replaced and a token file mounted.

Validate rules/config with their actual parsers:

```powershell
docker run --rm --entrypoint promtool -v "${PWD}/monitoring:/etc/prometheus" prom/prometheus:v3.4.1 check config /etc/prometheus/prometheus.yml
docker run --rm --entrypoint promtool -v "${PWD}/monitoring:/etc/prometheus" prom/prometheus:v3.4.1 test rules /etc/prometheus/alerts.test.yml
docker run --rm --entrypoint amtool -v "${PWD}/monitoring:/etc/alertmanager" prom/alertmanager:v0.28.1 check-config /etc/alertmanager/alertmanager.yml
```

## Real network timeout and recovery

```powershell
$env:PAYMENT_RESPONSE_DELAY_SECONDS='4'
docker compose up -d --force-recreate payments
$order = Invoke-RestMethod -Method Post http://localhost:8000/orders -ContentType application/json -Body '{"amount":1234,"currency":"INR"}'
$order # pending: each two-second request times out after the payment was committed
docker compose restart orders
$env:PAYMENT_RESPONSE_DELAY_SECONDS='0'
docker compose up -d --force-recreate payments
Start-Sleep 10
Invoke-RestMethod "http://localhost:8000/orders/$($order.id)" # paid, one transaction
docker compose exec mongo mongosh payments --quiet --eval "db.transactions.find({key:'order:$($order.id)'}).toArray()"
```

Restarting Orders reloads persisted pending records. Concurrent worker/request retries share the same key. Payments commits before delay. Mongo volumes survive container recreation. Never delete the volume while testing restart recovery.

## Alert demonstrations

Use a Python environment with requirements installed. HighErrorRate means more than 10% HTTP 5xx with at least 0.2 requests/sec, sustained for two minutes, measured over a rolling two-minute window. SlowResponses means histogram-estimated P95 exceeds one second for two minutes. Allow 4–6 minutes for sampling, window accumulation and pending duration; view Prometheus Alerts then Alertmanager. Local probes are included in these metrics.

```powershell
# SlowResponses: delay responses after payment persistence.
$env:PAYMENT_RESPONSE_DELAY_SECONDS='2'
docker compose up -d --force-recreate payments
python scripts/alert_load.py slow --seconds 360
$env:PAYMENT_RESPONSE_DELAY_SECONDS='0'
docker compose up -d --force-recreate payments
# HighErrorRate: keep APIs alive while making readiness fail.
docker compose stop mongo
python scripts/alert_load.py errors --seconds 360
docker compose start mongo
```

The load generator uses five workers and new keys. The slow test writes test transactions; local database size grows. Slow alert should resolve once fresh traffic is fast; error alert resolves after MongoDB returns. `for` avoids firing on brief spikes. Bucket resolution makes P95 approximate. Business declines remain 200 and need a separate business metric in production. Production thresholds require a measured SLO and traffic profile.

## Minikube application deployment

```powershell
minikube start --driver=docker --cpus=4 --memory=6144
kubectl create namespace payments
minikube image build -t payments-orders:dev -f services/orders.Dockerfile .
minikube image build -t payments-payments:dev -f services/payments.Dockerfile .
kubectl -n payments create secret generic payments-runtime --from-literal=MONGO_URI=mongodb://demo-mongo:27017
helm lint helm/payments
helm upgrade --install demo helm/payments -n payments -f helm/payments/values-dev.yaml --wait --timeout 5m
kubectl -n payments get pods,svc,pvc
kubectl -n payments port-forward svc/demo-orders 8000:8000
# Another terminal:
kubectl -n payments port-forward svc/demo-payments 8001:8000
```

The release name `demo` matches the Secret URI above. If you choose another name update the host in the Secret. Do not run port-forwards on ports occupied by Compose: stop Compose first, or use local ports 18000/18001. Readiness checks MongoDB; Orders also checks Payments readiness. Liveness only checks the local process. Startup connects and builds indexes; a missing database at startup may restart the process until it becomes reachable. The single PVC is for a local demonstration, not MongoDB high availability.

To independently deploy one API disable the other with `--set services.orders.enabled=false` or `--set services.payments.enabled=false`; set `--set config.paymentsUrl=http://OTHER_RELEASE-payments:8000` when deploying against a separate Payments release. The two images/processes have no shared runtime code outside their packaged common module.

## Minikube monitoring

First stop Compose to free host ports. These manifests use the same repository configs and provisioned dashboard; static scrape targets resolve the Helm Services in the `payments` namespace.

```powershell
kubectl -n payments create configmap prometheus-config --from-file=prometheus.yml=monitoring/prometheus-k8s.yml --from-file=alerts.yml=monitoring/alerts.yml
kubectl -n payments create configmap alertmanager-config --from-file=alertmanager.yml=monitoring/alertmanager.yml
kubectl -n payments create configmap grafana-datasource --from-file=default.yml=monitoring/grafana/provisioning/datasources/default.yml
kubectl -n payments create configmap grafana-provider --from-file=default.yml=monitoring/grafana/provisioning/dashboards/default.yml
kubectl -n payments create configmap grafana-dashboard --from-file=payments.json=monitoring/grafana/dashboards/payments.json
kubectl -n payments create secret generic grafana-auth --from-literal=password=local-demo-change-me
kubectl -n payments apply -f monitoring/kubernetes.yaml
kubectl -n payments rollout status deployment/prometheus
kubectl -n payments rollout status deployment/grafana
kubectl -n payments rollout status deployment/alertmanager
kubectl -n payments port-forward svc/prometheus 9090:9090
# Separate terminals:
kubectl -n payments port-forward svc/grafana 3000:3000
kubectl -n payments port-forward svc/alertmanager 9093:9093
```

Run the same API examples through service port-forwarding. For slow alerts use `helm upgrade demo helm/payments -n payments -f helm/payments/values-dev.yaml --set config.paymentDelay=2 --wait`, then the load generator. Restore delay to zero afterward. For error alerts scale `demo-mongo` StatefulSet to zero, send readiness traffic through Payments port-forward, then scale it to one. Requests through Kubernetes Services cease when readiness removes endpoints; port-forward connects directly to a pod, so dependency-failure traffic remains possible. Minikube monitoring is a separate local manifest stack, single replica with ephemeral data. ConfigMap updates require restarting deployments; dashboard/config setup must use the same release name or adjust scrape targets.

## Upgrade and rollback

Development release with a distinct image tag:

```powershell
minikube image build -t payments-orders:demo-v2 -f services/orders.Dockerfile .
minikube image build -t payments-payments:demo-v2 -f services/payments.Dockerfile .
helm upgrade demo helm/payments -n payments -f helm/payments/values-dev.yaml --set services.orders.tag=demo-v2 --set services.payments.tag=demo-v2 --wait --atomic --timeout 5m
helm history demo -n payments
helm rollback demo 1 -n payments --wait --timeout 5m
kubectl -n payments get deployments
```

Revision 1 must be a known working revision; inspect history before choosing. Rollback restores Kubernetes configuration/images, not database contents. Database changes must be backward compatible. This example rebuilds identical source under a second tag to demonstrate release mechanics; actual CI releases use full commit SHA tags.

Production template example (requires separately provisioned managed MongoDB and published images):

```powershell
# Supply URI securely through your secret manager; do not commit it.
kubectl -n payments create secret generic payments-production-runtime --from-literal=MONGO_URI=$env:PRODUCTION_MONGO_URI
helm upgrade --install demo helm/payments -n payments -f helm/payments/values-prod.yaml --set services.orders.image=YOUR_USER/payments-orders --set services.payments.image=YOUR_USER/payments-payments --set services.orders.tag=FULL_COMMIT_SHA --set services.payments.tag=FULL_COMMIT_SHA --wait --atomic
```

Secret values are external to the chart. Changing secrets needs `kubectl rollout restart deployment/demo-orders deployment/demo-payments -n payments`. Production values disable local MongoDB and increase resources/replicas. Never apply placeholder repositories/tags as a real release.

## Troubleshooting

- Pending order: inspect JSON `payment_retry` logs, dependency readiness, stable payment key and MongoDB transaction. Restore dependency and wait for worker. 409/permanent 4xx require operator investigation, not new payment keys.
- CrashLoopBackOff: check Mongo URI/Secret, DNS, index creation and logs with `kubectl -n payments logs deployment/demo-payments --previous`.
- ImagePullBackOff: verify repository, full SHA and registry authentication; development images must be loaded into Minikube and use Never pull policy.
- Failed readiness: inspect `/health/ready`, MongoDB pod/PVC and Payments status. Liveness remaining healthy during database outage is expected.
- Missing metrics/dashboard: generate traffic, check Targets, datasource URL and provisioning mounts. Unknown routes use a single label.
- Helm: inspect `helm status demo -n payments`, `helm history demo -n payments`, and `kubectl -n payments describe pod POD_NAME`. Readiness failure can trigger `--atomic` rollback.

## Cleanup

```powershell
docker compose down # preserves Mongo data
helm uninstall demo -n payments
kubectl -n payments delete -f monitoring/kubernetes.yaml
# Destructive cleanup only when you intend to erase local data:
docker compose down -v
kubectl delete namespace payments # deletes PVC and namespace resources
minikube delete
```

Stop port-forward terminals with Ctrl+C. Removing a Helm release can retain StatefulSet PVCs; deleting namespace erases those claims. Keep backups for any non-disposable data.

## Automated live monitoring verifier

`scripts/verify_monitoring.py` can reproduce the live alert proof without Docker if native MongoDB, Prometheus and Alertmanager binaries are available. It allocates loopback ports, starts isolated processes, stops its own MongoDB, generates readiness 503 traffic and waits up to five minutes for both alerts to fire and reach Alertmanager. It writes evidence under `.run/monitoring-demo/` and always stops its processes. Windows binaries are available from the official MongoDB download host and the Prometheus/Alertmanager GitHub release pages; pass their executable paths:

```powershell
python scripts/verify_monitoring.py --mongo-bin PATH_TO_MONGOD --prometheus-bin PATH_TO_PROMETHEUS --alertmanager-bin PATH_TO_ALERTMANAGER --seconds 300
```

This optional verifier demonstrates the real metric/rule/delivery flow. The Compose and Minikube deployment commands remain the portfolio deployment paths. Deterministic alert unit tests are part of CI and do not require waiting five minutes.

## Deployed-stack smoke tests and CI evidence

After Compose starts, verify API outcomes, duplicate/conflicting payment keys, both Prometheus targets and Grafana's provisioned dashboard/datasource:

```powershell
python scripts/smoke_stack.py --prometheus http://localhost:9090 --grafana http://localhost:3000 --evidence .run/compose-smoke.json
```

The same smoke script works through Minikube port-forwards. Use `--previous .run/install.json` after upgrade/rollback to confirm the previously created successful order and transaction ID are unchanged. CI performs installation, upgrade and rollback automatically and uploads `compose-evidence` and `minikube-evidence` artifacts. Image publication waits for both deployment jobs as well as the real MongoDB test job. See `verification.md` for completed run links and evidence.

## Windows image loading compatibility

Minikube 1.35.0's image cache calls the retired Windows `wmic` tool. If `minikube image load` reports that `wmic` is missing, transfer a Docker archive to the named cluster's Docker runtime instead. The example below uses profile `payments` and Kubernetes 1.32.0:

```powershell
minikube start -p payments --driver=docker --cpus=2 --memory=4096 --kubernetes-version=v1.32.0
docker compose build orders payments
docker tag paymentmicroservices-orders:latest payments-orders:dev
docker tag paymentmicroservices-payments:latest payments-payments:dev
New-Item -ItemType Directory -Path .run -Force
docker save -o .run/kubernetes-images.tar payments-orders:dev payments-payments:dev
docker cp .run/kubernetes-images.tar payments:/var/payments-images.tar
docker exec payments docker load -i /var/payments-images.tar
```

Continue the application/monitoring commands above using `kubectl --context=payments` and Helm `--kube-context payments`. Use `minikube -p payments` for this profile's commands and `minikube delete -p payments` for cleanup. Preloading MongoDB and monitoring images the same way can avoid downloads inside the cluster. Use `/var` for the archive because the node's `/tmp` is a temporary filesystem. This example requires Minikube's Docker container runtime.

## Native Grafana proof

The optional `scripts/verify_grafana.py` verifier starts isolated MongoDB, both APIs, Prometheus and Grafana using native binaries. It validates provisioning and datasource health, saves `docs/grafana-evidence.json`, generates traffic for visual QA, and shuts down all processes. Supply explicit binary and workspace paths:

```powershell
python scripts/verify_grafana.py --root "$PWD" --mongo-bin PATH_TO_MONGOD --prometheus-bin PATH_TO_PROMETHEUS --grafana-bin PATH_TO_GRAFANA --grafana-home PATH_TO_GRAFANA_HOME --keep-seconds 180
```

The screenshot in `docs/grafana-dashboard.jpg` was captured from this live verification. Native checks complement the primary Compose/Minikube deployment paths.
