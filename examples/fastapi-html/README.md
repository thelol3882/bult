# fastapi-html

Demo application for the bult **FastAPI preset** that renders an HTML page.
No Dockerfile on purpose: the platform supplies one.

- `GET /` — page with the replica (container hostname), uptime, `Host`,
  client IP and `X-Forwarded-For`: refresh it behind the ingress to see which
  replica answered and whether `FORWARDED_ALLOW_IPS` lets uvicorn trust the proxy
- `GET /healthz` — liveness probe

Run locally: `pip install -r requirements.txt && PORT=8000 uvicorn main:app --port 8000`
