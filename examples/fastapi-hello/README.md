# fastapi-hello

Demo application for the bult **FastAPI preset**. It has no Dockerfile on
purpose: the platform supplies one.

- `GET /` — app name, hostname (container ID — shows which replica answered), `$PORT`, uptime
- `GET /healthz` — liveness probe

Run locally: `pip install -r requirements.txt && PORT=8000 uvicorn main:app --port 8000`
