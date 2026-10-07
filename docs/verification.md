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
- Initialized the workspace as a Git repository on main; no remote or publishing account has been invented.

## Remaining environment-dependent checks

- Docker daemon/image builds and the complete Compose container stack were not executed. Docker Desktop has now been installed in per-user mode. Its Welcome/first-run screen must be completed; the Linux engine currently returns an HTTP 500 rather than a ready response. CI now builds both API images on PRs as well as main pushes.
- Kubernetes API admission, Minikube deployment, Kubernetes probes, Helm release upgrade/rollback were not executed. A container engine and Minikube cluster are required; exact commands are in the runbook.
- Grafana provisioning and visual rendering are now verified natively. Running the same dashboard in Compose/Kubernetes is covered by the new CI jobs, which have not run remotely yet.
- GitHub Actions has not run remotely and Docker Hub images have not been published. Configure the documented repository Secrets and push main to run that workflow.
- Alertmanager reception is verified; external notifications are deliberately unconfigured for this local demo.

The repository implementation and available local checks are complete; the items above are deployment evidence still requiring the relevant runtime/accounts, rather than claims of completed deployment.

## Local verification environment

The host Python virtual-environment bootstrap failed, so dependencies were installed into ignored workspace directories. Windows async tests required approved local socket access outside the restricted sandbox. A normal Python installation can use the README virtual-environment commands. Downloaded tools and test data are ignored by Git and excluded from Docker build contexts.

## Host prerequisites for the remaining deployment

Docker Desktop is now installed per user from Docker's official installer, whose Authenticode signature was verified as valid and signed by Docker Inc. WSL 2.6.3 is available, and workspace-local Minikube 1.35.0/kubectl 1.32.0 were downloaded. Docker's Welcome setup still needs completion before the engine is ready. GitHub CLI was authorized by the user and authenticated as vasun26shriya. Creation of vasun26shriya/containerised-payments-microservices is pending the user's explicit public/private visibility choice. Docker Hub publishing still requires its username and GitHub Secrets. No tokens are stored in the project.
