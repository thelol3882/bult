"""Demo app for the bult FastAPI preset: an HTML page that shows which
replica answered and what the ingress passed along.

Preset conventions: dependencies in requirements.txt, the ASGI app is `app`
in main.py, the port comes from $PORT. No Dockerfile — the preset provides it.
"""

import html
import os
import socket
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="fastapi-html")
STARTED_AT = time.time()

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{host} · bult</title>
<style>
  :root {{ color-scheme: light; }}
  body {{
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: #0b1622;
    background: linear-gradient(180deg, #00afca 0%, #7fd6e4 55%, #f5f8fa 100%);
  }}
  .card {{
    width: min(560px, calc(100vw - 32px)); padding: 32px; border-radius: 20px;
    background: rgba(255, 255, 255, .92); box-shadow: 0 20px 60px rgba(11, 22, 34, .18);
  }}
  h1 {{ margin: 0 0 4px; font-size: 32px; letter-spacing: -.02em; }}
  .sub {{ margin: 0 0 24px; color: #5b6b7b; }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 10px 20px; margin: 0; }}
  dt {{ color: #5b6b7b; }}
  dd {{ margin: 0; font-family: ui-monospace, "JetBrains Mono", monospace; word-break: break-all; }}
  .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%;
          background: #fec50c; margin-right: 8px; vertical-align: middle; }}
</style>
</head>
<body>
  <main class="card">
    <h1><span class="dot"></span>Hello from bult</h1>
    <p class="sub">Refresh to see which replica answers.</p>
    <dl>
      <dt>Replica</dt><dd>{hostname}</dd>
      <dt>Uptime</dt><dd>{uptime}</dd>
      <dt>Host</dt><dd>{host}</dd>
      <dt>Client IP</dt><dd>{client}</dd>
      <dt>Forwarded for</dt><dd>{forwarded}</dd>
    </dl>
  </main>
</body>
</html>
"""


def _uptime() -> str:
    seconds = int(time.time() - STARTED_AT)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> str:
    # Values come from the request: escape them before putting them into HTML.
    return PAGE.format(
        hostname=html.escape(socket.gethostname()),
        uptime=_uptime(),
        host=html.escape(request.headers.get("host", "—")),
        client=html.escape(request.client.host if request.client else "—"),
        forwarded=html.escape(request.headers.get("x-forwarded-for", "—")),
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
