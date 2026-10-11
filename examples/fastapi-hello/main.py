"""Demo app for the bult FastAPI preset (requirements.txt, `app` in main.py, port from $PORT)."""

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
