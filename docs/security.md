# Security demonstration and production boundaries

## Authenticated local deployment

Compose 2.24.4 or later is required for the overlay's `!override` entries.

```powershell
python scripts/create_demo_secrets.py
docker compose -p payments-secure -f compose.yaml -f compose.secure.yaml up --build -d --wait --wait-timeout 240
python scripts/verify_secure.py --evidence .run/secure-verification.json
python scripts/backup_restore.py --evidence .run/restore-verification.json
```

This uses a separate volume and ports: Orders 28000, Payments 28001, MongoDB 28017, Prometheus 29090, Grafana 23000, Alertmanager 29093. Existing development data stays in its original Compose project.

The generator creates random per-service API tokens, MongoDB passwords and Grafana password under ignored `.run/secure/secrets`. It never overwrites existing files or prints credentials. On Unix the parent directory is private; mounted files are readable by container users. Protect the directory with your Windows account ACL and never commit or upload it. Compose secrets are local file mounts, not a managed vault.

Each business endpoint requires its service's bearer token. Orders sends the Payments token on its outbound requests. Probes, metrics and Swagger remain open for local/internal operations; restrict them with production network controls. `API_AUTH_REQUIRED=true` fails startup when no usable token exists. Tokens must contain at least 32 characters. `API_TOKEN_FILE`, `PAYMENTS_API_TOKEN_FILE`, and `MONGO_URI_FILE` load mounted secrets; providing both a variable and its `_FILE` variant is rejected.

MongoDB initialization creates separate `readWrite` users for the Orders and Payments databases. The verifier checks permitted access and rejected cross-database reads. Initial-user scripts run only for an empty secure volume. Changing a password file alone does not rotate an existing database user's password; perform coordinated database credential rotation and service restart.

## Kubernetes production configuration

Production values enable machine-token authentication and require an existing `payments-production-runtime` Secret containing four keys:

| Key | Consumer |
|---|---|
| ORDERS_MONGO_URI | Orders |
| PAYMENTS_MONGO_URI | Payments |
| ORDERS_API_TOKEN | Orders |
| PAYMENTS_API_TOKEN | Payments and Orders outbound client |

Create the Secret from protected files, avoiding credentials in shell arguments:

```powershell
kubectl -n payments create secret generic payments-production-runtime --from-file=ORDERS_MONGO_URI=.run/secure/secrets/orders-mongo-uri --from-file=PAYMENTS_MONGO_URI=.run/secure/secrets/payments-mongo-uri --from-file=ORDERS_API_TOKEN=.run/secure/secrets/orders-api-token --from-file=PAYMENTS_API_TOKEN=.run/secure/secrets/payments-api-token
```

For an external database, prepare files with its actual scoped connection URIs; local Compose hostnames are not usable from Kubernetes. Apply the production Helm values with verified image SHA tags as described in the runbook. Secrets are projected as files with only the keys each service needs. Kubernetes Secrets require cluster access controls and encryption at rest; base64 encoding is not encryption. A cloud secret controller/KMS can provision the same keys, but no paid external vault has been connected here.

Applications load credentials at startup. Coordinate key rotation and roll out both services; this demonstration does not support an overlapping old/new token window. Production requires TLS, client identity and roles, network policy, rate limiting and audited access. These are deployment-specific additions, not implied by the machine-token demo.

## Backups and restores

The backup helper reads the root credential inside the secure Mongo container, uses temporary tool configuration, and never records its value. It dumps both databases to compressed archives and restores into random temporary databases. It compares every document and index definition before removing those temporary databases. See [verified restore evidence](backup-evidence.json).

The local drill runs without concurrent writes. Separate dumps on a standalone server do not provide a cross-database consistent production snapshot. Use a replica-set-aware backup procedure or quiesce writes, encrypt offsite backups, set retention and access controls, and regularly test disaster recovery. Ignored local archives are useful for practice, not an offsite backup strategy.

## Image scanning

CI builds and scans both images with a pinned official Grype release whose archive checksum is verified. JSON reports are retained as Actions artifacts. The scan jobs must execute successfully before publication; vulnerability findings are currently reported rather than blocked by severity. Review fixes and establish an explicit severity/exception policy before adopting a production release gate. A successful job does not mean no vulnerabilities were found.

The initial scan prompted a runtime update to digest-pinned Python 3.13.16 on Debian trixie, FastAPI 0.142.2, Starlette 1.7.0 and PyMongo 4.18.2. Pip is removed after dependency installation because runtime containers do not need a package manager. Rebuild images to update dependencies; do not install packages into a running container.

| Package/advisory matches per image | Initial image | Patched image |
|---|---:|---:|
| Critical | 19 | 0 |
| High | 153 | 55 |
| Total | 455 | 161 |
| Python package findings | 17 | 0 |

[Initial evidence](security-scan-before.json) and [patched evidence](security-scan-summary.json) identify exact revisions and scan runs. Remaining High matches are base-system packages for which this scan lists no distribution fix. Two Medium Python-binary findings list fixes only in Python 3.15; this project retains Python 3.13. These results need production risk assessment and ongoing upstream updates. The images are not vulnerability-free.

Keep database credentials, bearer tokens, backup archives and full environment dumps out of evidence and public artifacts. The recorded API replay contains only request payloads and responses.

References: [Compose merge](https://docs.docker.com/reference/compose-file/merge/), [Compose secrets](https://docs.docker.com/reference/compose-file/secrets/), [MongoDB restore](https://www.mongodb.com/docs/database-tools/mongorestore/), [Grype installation](https://oss.anchore.com/docs/installation/grype/).
