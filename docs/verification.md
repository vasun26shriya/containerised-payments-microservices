# Verification record

Verified on 2026-10-07 in the provided Windows workspace with Python 3.13.7.

## Executed successfully

- Downloaded workspace-local MongoDB 7.0.21, Helm 3.17.3, Compose 2.36.2, Prometheus 3.4.1 and Alertmanager 0.28.1. No system installation was needed.
- Ran the complete test suite with a real MongoDB on loopback port 27028: **16 passed, no skips**.
- Verified sequential and 30 concurrent duplicate payments, concurrent payload conflicts, the actual MongoDB unique index, success/decline outcomes, order creation/retrieval, temporary 503 retries, ambiguous timeout recovery, health checks and normalized metrics.
- The real TCP test starts both APIs as separate Uvicorn processes, forces actual HTTP read timeouts after payment persistence, restarts both processes, and confirms recovery using the original transaction ID with one MongoDB record.
- Passed Ruff checks and formatting checks on all service, test and script Python files.
- Passed `docker-compose config --quiet` with the standalone Compose executable; this validates configuration without a Docker daemon.
- Passed Helm lint for development and production values with the chart JSON schema. Rendered eight development resources and six production resources; parsed the resulting YAML and checked API probes.
- Passed Prometheus configuration checks (only its container rule-file path was adapted to a local relative path), both alert-rule checks and alert-rule unit tests. Tests verify sustained firing, pending duration and a below-threshold case.
- Passed Alertmanager configuration validation.
- Started actual Prometheus, Alertmanager, Orders and Payments processes with an isolated MongoDB. Stopped that MongoDB and generated readiness failure traffic. **HighErrorRate and SlowResponses both fired and were received by Alertmanager**, using the repository's unchanged two-minute rules and 15-second scrape/evaluation intervals.
- Recorded the live alert evidence in [monitoring-evidence.json](monitoring-evidence.json). The monitoring verifier shuts down its isolated processes in a `finally` block.
- Ran Grafana 12.0.1 with the provisioned dashboard and Prometheus datasource against native Orders/Payments and MongoDB. Deployed-stack smoke checks passed, both Prometheus targets were UP, Grafana confirmed the dashboard was provisioned and datasource health was OK. Saved [Grafana evidence](grafana-evidence.json).
- Signed into the loopback Grafana demo through the browser, inspected live request-rate and latency data for both services, confirmed zero error-rate data, and saved [the dashboard screenshot](grafana-dashboard.jpg).
- Added Compose and pinned Minikube CI deployment jobs, including persisted-order checks after install/upgrade/rollback. The expanded workflow passed Actionlint 1.7.7 validation and the new smoke/verifier scripts passed Ruff checks.
- Published the source to the user-approved public repository: https://github.com/vasun26shriya/containerised-payments-microservices.

## Container and remote CI verification

- Installed Docker Desktop from its official signed installer and started its Linux engine.
- Built both API images and started all six Compose services. Both API healthchecks and MongoDB were healthy.
- Passed deployed Compose API, idempotency, conflict, Prometheus targets and Grafana provisioning checks; saved [Compose evidence](compose-evidence.json).
- Repeated all 16 integration tests against the running Compose MongoDB: 16 passed, no skips.
- [GitHub Actions run 37629765160](https://github.com/vasun26shriya/containerised-payments-microservices/actions/runs/37629765160) passed test, compose-smoke and minikube-smoke on commit 8dff22f. CI deployed Kubernetes 1.32.0, checked the application and monitoring, upgraded the Helm release, successfully rolled back to revision 1 and verified the original persisted order after both changes.
- The first image publication attempt failed because Docker Hub credentials were missing. The owner then configured both GitHub Secrets. [Run 37632549017](https://github.com/vasun26shriya/containerised-payments-microservices/actions/runs/37632549017) on commit 837cea7 passed every job, including both image publication jobs. Registry inspection confirmed both linux/amd64 images and their manifests.
- Fixed CI artifact retention for the ignored `.run` directory using `include-hidden-files: true`; the earlier successful run has logs but did not retain its hidden-directory artifacts.

## Published release

Tag: `837cea7fbcdf1f9bcc265121e3ee0e85617f3e56`.

- Orders: `shriyavsingh/payments-orders`, index digest `sha256:3d3606b4e997ce4f8cb62346237bea9f386e5c704e097097bd0898ce57d8194a`.
- Payments: `shriyavsingh/payments-payments`, index digest `sha256:951e3dbc6a47de1f4ba735c44e40b5b9f1cb38a6b494473c581aa3b83e908806`.
- Retained CI [install](ci-evidence/install.json), [upgrade](ci-evidence/upgrade.json), [rollback](ci-evidence/rollback.json) and [Helm history](ci-evidence/helm-history.txt) evidence came from successful run 37632549017.

## Local deployment and environment

Local Minikube profile `payments` runs Kubernetes 1.32.0 with the Docker driver, two CPUs and 4 GiB RAM. All six pods are ready and the MongoDB PVC is bound. The first startup's Windows SSH-key permission command failed; a clean retry succeeded. Minikube image loading then encountered the retired WMIC dependency, so built images were transferred through a Docker archive into the node runtime.

Local [installation](minikube-install-evidence.json), [upgrade](minikube-upgrade-evidence.json), [rollback](minikube-rollback-evidence.json) and [Helm history](helm-history.txt) checks all passed. Revision 3 was the corrected working baseline, revision 4 demonstrated the second image tags, and revision 5 rolled back to revision 3. The original order and transaction were unchanged. These tags use identical application source to demonstrate release mechanics.

Host load exposed intermittent timeouts in the development MongoDB shell probe. Compose and Helm now use a 15-second probe timeout and a 20-second interval. Monitoring deployments now wait for HTTP readiness before port-forwarding; this fixed a premature Grafana connection failure. Dev/prod Helm lint and Compose configuration passed after the changes. The corrected Compose stack passed again, including preservation of the earlier order across MongoDB recreation.

Local Kubernetes endpoints are Orders `http://127.0.0.1:18000/docs`, Payments `http://127.0.0.1:18001/docs`, Prometheus `http://127.0.0.1:19090`, Grafana `http://127.0.0.1:13000` and Alertmanager `http://127.0.0.1:19093`. Port-forward process IDs are recorded in ignored `.run/kubernetes-forward-pids.txt`; they must stay running for these URLs. Compose also remains running on the documented standard ports.

The host Python virtual-environment bootstrap failed, so dependencies were installed into ignored workspace directories. Windows async tests required approved local socket access outside the restricted sandbox. A normal Python installation can use the README virtual-environment commands. Downloaded tools and test data are ignored by Git and excluded from Docker build contexts.

Alertmanager reception is verified; external notification delivery remains deliberately unconfigured for the local demo. No account tokens are stored in the project. Docker cloud promotional credits are separate from this local project and are not required to run it.


