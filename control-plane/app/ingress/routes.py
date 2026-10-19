"""Render the full desired routes and hand them to the ingress sidecar (protocol: docs/architecture/ingress.md)."""

import asyncio
import json
import os
import shutil
from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

type LbAlgorithm = Literal["round_robin", "least_conn", "ip_hash"]

PROXY_CONNECT_TIMEOUT = "3s"  # a dead node must not stall requests for the 60 s default
UPSTREAM_ZONE_SIZE = "64k"
UPSTREAM_MAX_FAILS = 3
UPSTREAM_FAIL_TIMEOUT = "10s"
UPSTREAM_KEEPALIVE = 16
PROXY_NEXT_UPSTREAM_TRIES = 2
BACKEND_DOWN_BODY = '{"detail": "backend is not running", "code": "backend_unavailable"}'
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
class PathRoute:
    """`path` on the app's own domain is served by another app."""

    path: str  # '/api': validated by the apps domain (safe inside nginx config), no trailing slash
    target: str  # name of the app that answers


@dataclass(frozen=True)
class Route:
    """One app at <name>.<domain>, balanced over its replicas, plus the paths it hands to other apps."""

    name: str  # DNS label validated by Pydantic: safe inside nginx config
    upstreams: tuple[Upstream, ...]
    paths: tuple[PathRoute, ...] = ()


class RouteApplyError(Exception):
    """The sidecar rejected the version (`nginx -t` failed)."""


def _proxy_location(prefix: str, upstream: str) -> str:
    """A proxied location. No proxy_set_header here: one at this level would drop every
    header set in nginx.conf (Host, X-Forwarded-*); HTTP/1.1 and an empty `Connection`
    (needed by the upstream's keepalive) come from there too.

    Retries: another replica is tried only when the request may not have reached one (connect
    error, timeout), and nginx never repeats a non-idempotent request (POST) once it was sent.
    Do not add `non_idempotent`: "idempotent by the spec" is not "idempotent in the app".
    """
    return f"""\
    location {prefix} {{
        proxy_pass http://{upstream};
        proxy_connect_timeout {PROXY_CONNECT_TIMEOUT};
        proxy_next_upstream error timeout;
        proxy_next_upstream_tries {PROXY_NEXT_UPSTREAM_TRIES};
    }}
"""


def _backend_down_location(prefix: str) -> str:
    return f"""\
    location {prefix} {{
        types {{}}
        default_type application/json;
        add_header Cache-Control "no-store" always;
        return 503 '{BACKEND_DOWN_BODY}';
    }}
"""


def _path_locations(route: Route, live: AbstractSet[str]) -> str:
    """One location per path route, longest path first (nginx picks the longest prefix anyway).

    `/api/` with the slash: `/apiary` is not caught; a bare `/api` gets nginx's 301 to `/api/`
    when proxied, and an exact-match 503 when the target is down. The prefix is not stripped
    (no URI in proxy_pass): the target sees the same path as the client.
    """
    blocks = []
    for p in sorted(route.paths, key=lambda p: (-len(p.path), p.path)):
        if p.target in live:
            blocks.append(_proxy_location(f"{p.path}/", f"app_{p.target}"))
        else:
            blocks.append(_backend_down_location(f"= {p.path}"))
            blocks.append(_backend_down_location(f"{p.path}/"))
    return "\n".join(blocks) + ("\n" if blocks else "")


def render(
    routes: list[Route],
    domain: str,
    stopped: Iterable[str] = (),
    algorithm: LbAlgorithm = "round_robin",
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
    live = {r.name for r in routes}
    balancing = "" if algorithm == "round_robin" else f"    {algorithm};\n"
    for r in routes:
        servers = "\n".join(
            f"    server {u.node_ip}:{u.host_port} "
            f"max_fails={UPSTREAM_MAX_FAILS} fail_timeout={UPSTREAM_FAIL_TIMEOUT};"
            for u in r.upstreams
        )
        # `zone`: counters and failure marks shared by the worker processes.
        # `keepalive` goes after the balancing method.
        files[f"{r.name}.conf"] = f"""\
upstream app_{r.name} {{
    zone app_{r.name} {UPSTREAM_ZONE_SIZE};
{balancing}{servers}
    keepalive {UPSTREAM_KEEPALIVE};
}}

server {{
    listen 80;
    server_name {r.name}.{domain};

{_path_locations(r, live)}{_proxy_location("/", f"app_{r.name}")}}}
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

    def __init__(
        self, base_dir: Path, domain: str, algorithm: LbAlgorithm = "round_robin"
    ) -> None:
        self.domain = domain
        self.algorithm: LbAlgorithm = algorithm
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
        for filename, text in render(routes, self.domain, stopped, self.algorithm).items():
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


def with_paths(
    routes: Iterable[Route], paths: Mapping[str, Iterable[PathRoute]]
) -> list[Route]:
    """The routes with the path routes of their apps attached."""
    return [replace(r, paths=tuple(paths.get(r.name, ()))) for r in routes]


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
