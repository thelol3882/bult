# fastapi-load

Load generator app for the **FastAPI preset**: burns CPU or holds memory on demand, so the
Metrics tab has something to show. No Dockerfile on purpose: the platform supplies one.

- `GET /cpu?ms=100` — busy-loop for `ms` milliseconds (1–2000)
- `POST /memory?mb=32&seconds=120` — allocate `mb` MiB (1–128) and hold it for `seconds`
- `GET /` — replica name and memory held right now
- `POST /crash` — answers, then exits with code 1 (the replica dies)
- `POST /hang?seconds=60` — blocks the event loop for `seconds` (1–600): `/healthz` and everything else stall, the process stays alive
- `GET /healthz` — liveness probe (set it as the app's health check path)
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

## Watch the replica health on bult

1. Set the app's health check path to `/healthz` (without a path the check is a TCP connect, and a hung
   app still passes it: the kernel accepts connections while the process is stuck).
2. Crash: `curl -X POST -H 'Host: load.bult.localhost' http://localhost/crash` — one replica exits with code 1;
   it leaves the upstream at once and comes back after about 10 s. Repeat it quickly (the replica a request lands
   on varies) and the backoff grows (10 s, 20 s, 40 s); five deaths of one slot in 10 minutes make it `crashloop`.
3. Hang: `curl -m 1 -X POST -H 'Host: load.bult.localhost' 'http://localhost/hang?seconds=120'` — the replica fails
   its probe after about 30 s (3 probes), leaves the upstream, and after a minute more it is replaced.
