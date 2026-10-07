# Independent operations practice

Work from the repository root. Keep the baseline deployment separate from this lab. Use a fresh namespace for every release drill; the helper refuses an existing namespace.

## Startup and health

```powershell
docker compose up --build -d --wait --wait-timeout 240
docker compose ps
python scripts/smoke_stack.py --orders http://127.0.0.1:8000 --payments http://127.0.0.1:8001 --prometheus http://127.0.0.1:9090 --grafana http://127.0.0.1:3000 --evidence .run/practice-compose.json
```

Explain what each service owns before opening its logs. Confirm both readiness endpoints, Prometheus targets, and provisioned dashboard. Run the secured variant with [the security guide](security.md).

## Recovery exercise

```powershell
python scripts/record_demo.py --secure --orders http://127.0.0.1:28000 --payments http://127.0.0.1:28001 --exercise-recovery
python scripts/backup_restore.py --evidence .run/practice-restore.json
```

The first command exercises only the separate `payments-secure` Compose project. Observe pending becoming paid after restart, then explain why retrying a new payment key would be unsafe. The second backs up each service database, restores into random isolated databases, compares documents and indexes, and removes only its temporary restore databases. Backup archives remain under ignored `.run/backups`.

## Install, upgrade and rollback

Prerequisites: an existing Docker-driver Minikube profile/context named `payments`, Helm, kubectl, Docker, Python dependencies, and a cached `mongo:7.0.21` image in the node. See [runbook](runbook.md) for startup and the Windows image-transfer workaround.

```powershell
./scripts/release_demo.ps1 -Context payments -Namespace payments-demo
# Workspace-local tools, when they are not on PATH:
./scripts/release_demo.ps1 -Context payments -Namespace payments-demo-2 -Kubectl "$PWD/.tools/kubectl.exe" -Helm "$PWD/.tools/helm/windows-amd64/helm.exe"
```

The helper builds two local image tags from the same source to demonstrate release mechanics, transfers them into the node without requiring Windows WMIC, then installs, upgrades and rolls back. Each step verifies APIs and the original persisted order. It retains its lab namespace and saves JSON/history under `.run/release-demo`; its own port forwards are stopped. It does not deploy monitoring again. After a previous image transfer, `-ReuseImages` validates those existing node images and skips rebuilding/transferring them. Use a fresh namespace and `-Evidence .run/release-retry` for a retry. Loaded hosts have a ten-minute Helm timeout; stop heavy unrelated local work before the exercise.

## Troubleshooting checklist

| Symptom | Inspect | What to explain |
|---|---|---|
| API not ready | `docker compose logs --tail 100 orders mongo` | Database availability differs from process liveness. |
| Pending order | Payments logs and order state | Response loss is ambiguous; recovery uses the original key. |
| 401 in secure mode | Correct service token file and mount | Orders and Payments intentionally have different credentials. Never paste a token into logs. |
| Kubernetes pod not ready | `kubectl --context payments -n payments-demo describe pods` | Inspect events, image availability, probes and Secret keys. |
| Dashboard empty | Prometheus targets, time range, API traffic | A valid dashboard needs scraped samples and recent requests. |
| Upgrade fails | `helm history portfolio --kube-context payments -n payments-demo` | Atomic upgrades roll back configuration; inspect events before repeating. |

## Cleanup only your lab

After inspection, remove the exact namespace you created:

```powershell
helm uninstall portfolio --kube-context payments -n payments-demo
kubectl --context payments delete namespace payments-demo
docker compose -p payments-secure -f compose.yaml -f compose.secure.yaml down
```

Compose `down` preserves the secure Mongo volume. Removing a namespace deletes its development Mongo PVC and data. Never use `down -v`, delete a shared namespace, or delete the Minikube profile merely to troubleshoot. Preserve your backup before intentional data removal.
