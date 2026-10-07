# Five-minute project demo

Open [the recorded API demo](demo/index.html) locally. It replays saved real HTTP responses; it does not submit new payments. Use Presentation speed, or advance manually. The recording includes successful and declined orders, duplicate payment identity, a conflicting payload, and an ambiguous timeout recovered after an Orders restart.

| Time | Show | Explain |
|---|---|---|
| 0:00–0:30 | README architecture | Two independently deployed APIs own separate databases. This simulates payments; no money moves. |
| 0:30–1:20 | Successful and declined orders | Business decline is a recorded result, distinct from an unavailable dependency. |
| 1:20–2:00 | Duplicate and conflict steps | The same key returns the same transaction; changing its payload returns 409. |
| 2:00–2:50 | Timeout and recovery steps | A lost response does not prove failure. Durable pending orders reuse the original payment key after restart. |
| 2:50–3:30 | Grafana dashboard | Show request rate, latency and errors. Declines are HTTP 200 and do not count as server errors. |
| 3:30–4:20 | Helm history and release evidence | Show install, upgrade and rollback. Confirm the original order survives each deployment. |
| 4:20–5:00 | Security and CI evidence | Explain machine tokens, database isolation, a verified restore, and image scan reports. |

## Run and record it again

From the repository root, with Python dependencies installed:

```powershell
python scripts/create_demo_secrets.py
docker compose -p payments-secure -f compose.yaml -f compose.secure.yaml up --build -d --wait --wait-timeout 240
python scripts/record_demo.py --secure --orders http://127.0.0.1:28000 --payments http://127.0.0.1:28001 --exercise-recovery
python -m http.server 18080 --bind 127.0.0.1 --directory docs
```

Open http://127.0.0.1:18080/demo/index.html. The recovery exercise temporarily recreates the dedicated secure Payments service with a response delay and restarts secure Orders. It restores normal Payments configuration in `finally`. Do not run it against a shared deployment.

The API replay contains no tokens. Its timestamp and responses are in [session.json](demo/session.json). For a screen video, record this presentation and the dashboard with your preferred screen recorder; the repository contains an interactive recording, not a screen video.

The existing Kubernetes dashboard is at http://127.0.0.1:13000 when the runbook forwards are active; the Compose dashboard is at http://127.0.0.1:3000. See [dashboard screenshot](grafana-dashboard.jpg), [release practice](practice-guide.md), and [verification](verification.md).
