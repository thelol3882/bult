"""FastAPI preset demo: endpoints that burn CPU, hold memory, crash or hang on demand,
to watch the metrics and the replica health."""

import os
import socket
import threading
import time

from fastapi import FastAPI, Query, Request, Response

app = FastAPI(title="fastapi-load")
REPLICA = socket.gethostname()

# Memory held on purpose; each block is released after its time runs out.
_held: list[tuple[float, bytearray]] = []
_lock = threading.Lock()


@app.middleware("http")
async def add_replica_header(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Replica"] = REPLICA
    return response


def _release_expired() -> None:
    now = time.monotonic()
    with _lock:
        _held[:] = [(until, block) for until, block in _held if until > now]


@app.get("/")
def index() -> dict:
    _release_expired()
    with _lock:
        held_mb = sum(len(block) for _, block in _held) // (1024 * 1024)
    return {"replica": REPLICA, "held_mb": held_mb}


@app.get("/cpu")
def burn_cpu(ms: int = Query(100, ge=1, le=2000)) -> dict:
    """Busy-loop for `ms` milliseconds (a sync endpoint, so it runs in the thread pool)."""
    deadline = time.perf_counter() + ms / 1000
    spins = 0
    while time.perf_counter() < deadline:
        spins += 1
    return {"replica": REPLICA, "ms": ms, "spins": spins}


@app.post("/memory")
def hold_memory(
    mb: int = Query(32, ge=1, le=128), seconds: int = Query(120, ge=1, le=600)
) -> dict:
    """Allocate `mb` MiB and keep it for `seconds`; the page writes make it count as used memory."""
    _release_expired()
    block = bytearray(mb * 1024 * 1024)
    for i in range(0, len(block), 4096):
        block[i] = 1
    with _lock:
        _held.append((time.monotonic() + seconds, block))
        held_mb = sum(len(b) for _, b in _held) // (1024 * 1024)
    # Release on time even if no request comes in to trigger the cleanup.
    timer = threading.Timer(seconds + 0.1, _release_expired)
    timer.daemon = True
    timer.start()
    return {"replica": REPLICA, "held_mb": held_mb, "release_in_s": seconds}


@app.post("/crash")
def crash() -> dict:
    """Answer, then exit with code 1 a moment later: the replica dies like a crashing app."""
    timer = threading.Timer(0.2, os._exit, args=(1,))
    timer.daemon = True
    timer.start()
    return {"replica": REPLICA, "exit_code": 1, "in_s": 0.2}


@app.post("/hang")
async def hang(seconds: int = Query(60, ge=1, le=600)) -> dict:
    """Block the event loop (not just this request): /healthz and every other request stall
    for `seconds`, like an app stuck in a deadlock or a long synchronous call."""
    time.sleep(seconds)
    return {"replica": REPLICA, "hung_s": seconds}


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}
