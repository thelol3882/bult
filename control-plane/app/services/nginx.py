"""Ingress routes: render the full desired state and hand it to the sidecar.

Protocol (docs/architecture/ingress.md), shared volume BULT_INGRESS_DIR:
    desired/<gen>/<app>.conf   we write the FULL set, via desired/.tmp-<gen> + rename
    desired/LATEST             we write the latest <gen> (temp + os.replace)
    current -> desired/<gen>   the sidecar switches it after `nginx -t`
    status.json                the sidecar: {"generation", "ok", "error", "applied_at"}
"""

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.services.deploys import Deploy, DeployStore

PROXY_CONNECT_TIMEOUT = "3s"  # a dead node must not stall requests for 60 s (lesson 14)


def node_ip(runner_address: str) -> str:
    """'192.168.252.6:8080' -> '192.168.252.6'"""
    return runner_address.rsplit(":", 1)[0]


@dataclass(frozen=True)
class Route:
    """One app reachable at <name>.bult.localhost via one replica."""

    name: str  # DNS label, validated by Pydantic → safe inside nginx config
    node_ip: str
    host_port: int


class RouteApplyError(Exception):
    """The sidecar rejected the version (`nginx -t` failed); message = its error."""


def render(routes: list[Route]) -> dict[str, str]:
    """Filename -> nginx config text, one server block (+ upstream) per app."""
    files = {}
    for r in routes:
        files[f"{r.name}.conf"] = f"""\
upstream app_{r.name} {{
    server {r.node_ip}:{r.host_port};
    keepalive 16;
}}

server {{
    listen 80;
    server_name {r.name}.bult.localhost;

    location / {{
        proxy_pass http://app_{r.name};
        proxy_connect_timeout {PROXY_CONNECT_TIMEOUT};
    }}
}}
"""
    return files


def read_status(path: Path) -> dict | None:
    """Return status.json as a dict, or None if it's missing or half-written."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class RouteWriter:
    """Writes route versions into the shared volume and waits for the sidecar."""

    def __init__(self, base_dir: Path) -> None:
        self.desired_dir = base_dir / "desired"
        self.latest_file = self.desired_dir / "LATEST"
        self.status_file = base_dir / "status.json"
        self.desired_dir.mkdir(parents=True, exist_ok=True)

        # Continue numbering from where we left off (0 if nothing on disk yet)
        last_from_latest = 0
        if self.latest_file.exists():
            last_from_latest = int(self.latest_file.read_text().strip())

        last_from_status = 0
        status = read_status(self.status_file)
        if status:
            last_from_status = status.get("generation", 0)

        self.last_gen = max(last_from_latest, last_from_status)
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        """Hold it while collecting the desired routes and calling apply()."""
        return self._lock

    def apply(self, routes: list[Route]) -> int:
        """Write the next version atomically and return its number."""
        gen = self.last_gen + 1

        tmp_dir = self.desired_dir / f".tmp-{gen}"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir()
        for filename, text in render(routes).items():
            (tmp_dir / filename).write_text(text)
        os.rename(tmp_dir, self.desired_dir / str(gen))

        tmp_latest = self.desired_dir / "LATEST.tmp"
        tmp_latest.write_text(str(gen))
        os.replace(tmp_latest, self.latest_file)

        self.last_gen = gen
        return gen

    async def wait_applied(self, generation: int, timeout: float = 10.0) -> None:
        """Return when status.json reports this generation as ok.

        ok: false for this generation → RouteApplyError(error);
        no matching status in time → TimeoutError.
        """
        async with asyncio.timeout(timeout):
            while True:
                status = read_status(self.status_file)
                if status and status.get("generation") == generation:
                    if status.get("ok"):
                        return
                    raise RouteApplyError(status.get("error", "nginx -t failed"))
                await asyncio.sleep(0.2)


def running_routes(
    store: DeployStore,
    runner_addrs: dict[str, str],
    skip_app: str | None = None,
) -> list[Route]:
    """One route per app: its latest running deploy (skip_app is left out)."""
    latest: dict[str, Deploy] = {}
    for d in store.all():
        if d.status != "running" or d.app_name == skip_app:
            continue
        if d.app_name not in latest or d.created_at > latest[d.app_name].created_at:
            latest[d.app_name] = d

    return [
        Route(d.app_name, node_ip(runner_addrs[d.node]), d.host_port)
        for d in latest.values()
    ]
