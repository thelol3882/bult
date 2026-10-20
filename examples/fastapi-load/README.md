# fastapi-load

Load generator app for the **FastAPI preset**: burns CPU or holds memory on demand, so the
Metrics tab has something to show. No Dockerfile on purpose: the platform supplies one.

- `GET /cpu?ms=100` — busy-loop for `ms` milliseconds (1–2000)
- `POST /memory?mb=32&seconds=120` — allocate `mb` MiB (1–128) and hold it for `seconds`
- `GET /` — replica name and memory held right now
- `GET /healthz` — liveness probe
- every response carries `X-Replica` (container hostname)

The replica's memory limit is 256 MiB: holding much more than ~200 MiB on one replica gets it
OOM-killed (exit code 137), which is also worth seeing once.

Run locally: `pip install -r requirements.txt && PORT=8000 uvicorn main:app --port 8000`

## Watch the metrics on bult

1. Create app `load`: preset `fastapi`, subdir `examples/fastapi-load`; deploy; set replicas to 3.
2. CPU: `hey -z 3m -c 8 -host load.bult.localhost "http://localhost/cpu?ms=50"`
3. Memory: `curl -X POST -H 'Host: load.bult.localhost' 'http://localhost/memory?mb=64&seconds=180'`
   (one replica gets it — the others stay flat).
4. Open the app's Metrics tab: one line per replica.
