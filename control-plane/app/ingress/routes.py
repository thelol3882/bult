"""Render the full desired routes and hand them to the ingress sidecar (protocol: docs/architecture/ingress.md)."""

import asyncio
import json
import os
import shutil
from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

PROXY_CONNECT_TIMEOUT = "3s"  # a dead node must not stall requests for the 60 s default
STOPPED_SNIPPET = "/etc/nginx/bult/snippets/stopped.conf"  # lives in deploy/nginx


def node_ip(runner_address: str) -> str:
    """'192.168.252.6:8080' -> '192.168.252.6'."""
    return runner_address.rsplit(":", 1)[0]


@dataclass(frozen=True)
class Upstream:
    """One replica as nginx reaches it."""

    node_ip: str
    host_port: int


@dataclass(frozen=True)
class Route:
    """One app at <name>.<domain>, balanced over its replicas (nginx's default round-robin)."""

    name: str  # DNS label validated by Pydantic: safe inside nginx config
    upstreams: tuple[Upstream, ...]


class RouteApplyError(Exception):
    """The sidecar rejected the version (`nginx -t` failed)."""


def render(
    routes: list[Route], domain: str, stopped: Iterable[str] = ()
) -> dict[str, str]:
    """Filename -> nginx config: a server block and upstream per app, a 503 page per stopped app."""
    files = {}
    for name in stopped:
        files[f"{name}.conf"] = f"""\
server {{
    listen 80;
    server_name {name}.{domain};

    include {STOPPED_SNIPPET};
}}
"""
    for r in routes:
        servers = "\n".join(
            f"    server {u.node_ip}:{u.host_port};" for u in r.upstreams
        )
        files[f"{r.name}.conf"] = f"""\
upstream app_{r.name} {{
{servers}
    keepalive 16;
}}

server {{
    listen 80;
    server_name {r.name}.{domain};

    location / {{
        proxy_pass http://app_{r.name};
        proxy_connect_timeout {PROXY_CONNECT_TIMEOUT};
    }}
}}
"""
    return files


def read_status(path: Path) -> dict | None:
    """status.json as a dict, or None if missing or half-written."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class RouteWriter:
    """Writes route versions to the shared volume and waits for the sidecar."""

    def __init__(self, base_dir: Path, domain: str) -> None:
        self.domain = domain
        self.desired_dir = base_dir / "desired"
        self.latest_file = self.desired_dir / "LATEST"
        self.status_file = base_dir / "status.json"
        self.desired_dir.mkdir(parents=True, exist_ok=True)

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

    def apply(self, routes: list[Route], stopped: Iterable[str] = ()) -> int:
        """Write the next version atomically; return its generation.

        `stopped` names the apps that answer with the "stopped" page instead of a route.
        """
        gen = self.last_gen + 1

        tmp_dir = self.desired_dir / f".tmp-{gen}"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir()
        for filename, text in render(routes, self.domain, stopped).items():
            (tmp_dir / filename).write_text(text)
        os.rename(tmp_dir, self.desired_dir / str(gen))

        tmp_latest = self.desired_dir / "LATEST.tmp"
        tmp_latest.write_text(str(gen))
        os.replace(tmp_latest, self.latest_file)

        self.last_gen = gen
        return gen

    async def wait_applied(self, generation: int, timeout: float = 10.0) -> None:
        """Wait until the sidecar reports this generation; raise RouteApplyError if rejected, TimeoutError if silent."""
        async with asyncio.timeout(timeout):
            while True:
                status = read_status(self.status_file)
                if status and status.get("generation") == generation:
                    if status.get("ok"):
                        return
                    raise RouteApplyError(status.get("error", "nginx -t failed"))
                await asyncio.sleep(0.2)


class RunningDeploy(Protocol):
    """The part of a deploy that decides routing."""

    @property
    def id(self) -> str: ...
    @property
    def app_name(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def created_at(self) -> datetime | None: ...


class PlacedReplica(Protocol):
    """Where a replica listens."""

    @property
    def node(self) -> str: ...
    @property
    def host_port(self) -> int: ...


class StoredReplica(PlacedReplica, Protocol):
    @property
    def deploy_id(self) -> str: ...


def route_for(
    app_name: str,
    replicas: Iterable[PlacedReplica],
    node_ips: Mapping[str, str],
    routable: AbstractSet[str],
) -> Route | None:
    """The app's route over the replicas on routable nodes; None if there are none."""
    upstreams = tuple(
        Upstream(node_ips[r.node], r.host_port)
        for r in replicas
        if r.node in routable and r.node in node_ips
    )
    return Route(app_name, upstreams) if upstreams else None


def running_routes(
    deploys: Iterable[RunningDeploy],
    replicas: Iterable[StoredReplica],
    node_ips: Mapping[str, str],
    routable: AbstractSet[str],
    skip_app: str | None = None,
) -> list[Route]:
    """One route per app: the replicas of its latest running deploy that sit on routable
    nodes. An app with none is left out; skip_app is left out too.
    """
    latest: dict[str, RunningDeploy] = {}
    for d in deploys:
        if d.status != "running" or d.app_name == skip_app:
            continue
        # stored deploys always have a timestamp
        assert d.created_at is not None
        prev = latest.get(d.app_name)
        if prev is None or (prev.created_at and d.created_at > prev.created_at):
            latest[d.app_name] = d

    by_deploy: dict[str, list[StoredReplica]] = {}
    for r in replicas:
        by_deploy.setdefault(r.deploy_id, []).append(r)

    routes = []
    for d in latest.values():
        route = route_for(d.app_name, by_deploy.get(d.id, []), node_ips, routable)
        if route is not None:
            routes.append(route)
    return routes
