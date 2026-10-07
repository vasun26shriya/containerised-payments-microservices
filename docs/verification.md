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
- The image publication jobs failed because Docker Hub credentials were missing. DOCKERHUB_USERNAME is now configured; DOCKERHUB_TOKEN still requires the account owner's entry. Images have not yet been published.
- Fixed CI artifact retention for the ignored `.run` directory using `include-hidden-files: true`; the earlier successful run has logs but did not retain its hidden-directory artifacts.

## Remaining checks and local environment

Local Minikube deployment is in progress. Its first startup failed while applying owner-only SSH-key permissions on Windows; the exact permission command subsequently succeeded and the incomplete profile was restarted. Remote Kubernetes success above does not imply the Windows cluster has succeeded.

The host Python virtual-environment bootstrap failed, so dependencies were installed into ignored workspace directories. Windows async tests required approved local socket access outside the restricted sandbox. A normal Python installation can use the README virtual-environment commands. Downloaded tools and test data are ignored by Git and excluded from Docker build contexts.

Alertmanager reception is verified; external notification delivery remains deliberately unconfigured for the local demo. No account tokens are stored in the project. Docker cloud promotional credits are separate from this local project and are not required to run it.
