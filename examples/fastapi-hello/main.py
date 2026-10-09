"""Demo app for the bult FastAPI preset.

Preset conventions it follows: dependencies in requirements.txt, the ASGI
app is `app` in main.py, the port comes from $PORT (the preset passes it to
uvicorn). No Dockerfile here on purpose — the preset provides it.
"""

import os
import socket
import time

from fastapi import FastAPI

app = FastAPI(title="fastapi-hello")
STARTED_AT = time.time()


@app.get("/")
def root() -> dict:
    # hostname = container ID: shows which replica answered (handy behind nginx).
    return {
        "app": "fastapi-hello",
        "hostname": socket.gethostname(),
        "port": os.environ.get("PORT"),
        "uptime_s": round(time.time() - STARTED_AT, 1),
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
