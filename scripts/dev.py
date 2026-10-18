#!/usr/bin/env python3
"""bult dev tasks — a cross-platform replacement for the old Makefile.

Runs the same way on macOS/Linux (zsh, bash) and Windows (PowerShell, cmd):

    python3 scripts/dev.py <command>      # macOS / Linux
    py scripts\\dev.py <command>           # Windows

Only the Python standard library is used, so no virtualenv is needed.
Requirements on the machine: Python 3.10+, git, Docker; Multipass for the
node commands. Go is optional: without a local `go`, the agent is built and
tested inside the official golang image (see GO_IMAGE).

Configuration (environment variables, all optional):
    BULT_NODES         node VMs, space-separated   (default: bult-node-1 bult-node-2 bult-builder)
    BULT_BUILDER_NODE  the build node               (default: bult-builder)
    BULT_REGISTRY      registry address for builds  (default: 192.168.252.1:5050)
    BULT_CONTROL_PLANE_URL  API as the node VMs reach it (default: http://192.168.252.1:8000)
    BULT_GOARCH        node CPU architecture        (default: this machine's — Multipass VMs match the host)
    BULT_GO_DOCKER=1   build/test the agent in Docker even if `go` is installed
    DATABASE_URL       database for the db-* commands (default: the compose Postgres on localhost)

Control plane commands need `uv`; they start the compose Postgres when it is not running.

`smoke` runs scripts/smoke.py against a running stack (after `demo-up`): register, deploy,
redeploy, env, logs, stop/start, rollback, cancel, delete. Options after the command go to
the script (`smoke --keep`, `smoke --help`).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"
AGENT_BIN = AGENT_DIR / "bin" / "bultd"
AGENT_UNIT = ROOT / "deploy" / "systemd" / "bultd.service"
CP_DIR = ROOT / "control-plane"
# The compose Postgres as seen from the host (inside compose the host is `postgres`).
LOCAL_DATABASE_URL = "postgresql+asyncpg://bult:bult@localhost:5432/bult"

# Keep in sync with the `go` line of agent/go.mod.
GO_IMAGE = "golang:1.27"
# Named volumes: module downloads and the build cache survive between runs.
GO_CACHE_VOLUMES = ("bult-go-mod:/go/pkg/mod", "bult-go-build:/root/.cache/go-build")


# --- configuration --------------------------------------------------------


def host_goarch() -> str:
    """Go architecture of this machine (Multipass VMs use the host's)."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "amd64"
    sys.exit(f"unknown CPU architecture {machine!r}: set BULT_GOARCH")


NODES = os.environ.get("BULT_NODES", "bult-node-1 bult-node-2 bult-builder").split()
BUILDER_NODE = os.environ.get("BULT_BUILDER_NODE", "bult-builder")
# The VMs a demo needs: the builder and the runner(s) configured in control-plane/compose.yaml.
DEMO_NODES = os.environ.get("BULT_DEMO_NODES", "bult-node-1 bult-builder").split()
# Volumes `demo-down --wipe` removes: platform state only (registry images and Go caches stay).
STATE_VOLUMES = ("bult_postgres-data", "bult_ingress-routes")
REGISTRY = os.environ.get("BULT_REGISTRY", "192.168.252.1:5050")
# The API on the Multipass bridge (published next to 127.0.0.1 in control-plane/compose.yaml).
CONTROL_PLANE_URL = os.environ.get("BULT_CONTROL_PLANE_URL", "http://192.168.252.1:8000")
AGENT_PORT = 50051

# Dev node tokens: HMAC(secret, node name), so they are the same on every run and need no
# bookkeeping. The secret and the generated compose env file live in the gitignored .bult/.
BULT_DIR = ROOT / ".bult"
NODE_SECRET_FILE = BULT_DIR / "node-secret"
NODE_TOKENS_ENV = BULT_DIR / "node-tokens.env"
GOARCH = os.environ.get("BULT_GOARCH") or host_goarch()


# --- helpers --------------------------------------------------------------


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    """Run a command, echo it, stop the script on failure."""
    print("$", *(f"{k}={v}" for k, v in (env or {}).items()), " ".join(cmd), flush=True)
    full_env = {**os.environ, **env} if env else None
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture, env=full_env)
    if check and result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout if capture else ""


def version() -> str:
    """git describe for -X main.version, like the Makefile did."""
    result = subprocess.run(
        ["git", "describe", "--tags", "--always", "--dirty"],
        cwd=ROOT, text=True, capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "dev"


def use_docker_for_go() -> bool:
    return os.environ.get("BULT_GO_DOCKER") == "1" or shutil.which("go") is None


def go(args: list[str], *, env: dict[str, str] | None = None) -> None:
    """Run a go command in agent/: locally if go is installed, else in Docker."""
    env = env or {}
    if not use_docker_for_go():
        _run_env(["go", *args], env)
        return
    cmd = ["docker", "run", "--rm", "-v", f"{AGENT_DIR}:/src", "-w", "/src"]
    for volume in GO_CACHE_VOLUMES:
        cmd += ["-v", volume]
    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]
    run([*cmd, GO_IMAGE, "go", *args])


def _run_env(cmd: list[str], env: dict[str, str]) -> None:
    """Run cmd in agent/ with extra environment variables (portable: no `VAR=x cmd` shell syntax)."""
    print("$", *(f"{k}={v}" for k, v in env.items()), " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=AGENT_DIR, env={**os.environ, **env})
    if result.returncode != 0:
        sys.exit(result.returncode)


def node_secret() -> bytes:
    """The local secret node tokens are derived from (created on first use, mode 600)."""
    if not NODE_SECRET_FILE.exists():
        BULT_DIR.mkdir(exist_ok=True)
        NODE_SECRET_FILE.write_text(secrets.token_hex(32))
        NODE_SECRET_FILE.chmod(0o600)
    return NODE_SECRET_FILE.read_text().strip().encode()


def node_token(name: str) -> str:
    """The token a node reports with (64 hex characters)."""
    return hmac.new(node_secret(), f"bult-node:{name}".encode(), hashlib.sha256).hexdigest()


def ensure_node_tokens() -> None:
    """Write BULT_NODE_TOKENS for every node into the env file compose gives to the API."""
    BULT_DIR.mkdir(exist_ok=True)
    line = "BULT_NODE_TOKENS=" + ",".join(f"{n}={node_token(n)}" for n in NODES) + "\n"
    if not NODE_TOKENS_ENV.exists() or NODE_TOKENS_ENV.read_text() != line:
        NODE_TOKENS_ENV.write_text(line)
    NODE_TOKENS_ENV.chmod(0o600)


def node_ips() -> dict[str, str]:
    """Node name -> its first IPv4 address, from Multipass."""
    out = run(["multipass", "list", "--format", "json"], capture=True)
    return {vm["name"]: vm["ipv4"][0] for vm in json.loads(out)["list"] if vm.get("ipv4")}


def node_put_file(node: str, path: str, content: str, mode: str = "600") -> None:
    """Install a root-owned file on a node without the content ever appearing in a command line."""
    with tempfile.NamedTemporaryFile("w", suffix=".tmp", delete=False) as tmp:  # created 0600
        tmp.write(content)
    try:
        run(["multipass", "transfer", tmp.name, f"{node}:/tmp/bult-put.tmp"])
        node_sh(node, f"mkdir -p {os.path.dirname(path)} && "
                      f"install -m {mode} -o root -g root /tmp/bult-put.tmp {path} && rm -f /tmp/bult-put.tmp")
    finally:
        os.unlink(tmp.name)


def running_nodes() -> list[str]:
    """Nodes from NODES that Multipass reports as Running; warns about the rest."""
    out = run(["multipass", "list", "--format", "json"], capture=True)
    states = {vm["name"]: vm["state"] for vm in json.loads(out)["list"]}
    running = []
    for node in NODES:
        if states.get(node) == "Running":
            running.append(node)
        else:
            print(f"-- {node}: {states.get(node, 'not found')}, skipped")
    if not running:
        sys.exit("no running nodes — start them with: multipass start " + " ".join(NODES))
    return running


def node_sh(node: str, script: str, *, sudo: bool = True, capture: bool = False, check: bool = True) -> str:
    """Run a shell snippet on a node (always /bin/sh on the VM, whatever the host shell is)."""
    cmd = ["multipass", "exec", node, "--"]
    if sudo:
        cmd.append("sudo")
    return run([*cmd, "sh", "-c", script], capture=capture, check=check)


def node_reachable(node: str) -> bool:
    """False when `multipass exec` cannot reach the VM (e.g. no macOS Local Network permission)."""
    result = subprocess.run(["multipass", "exec", node, "--", "true"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"!! {node}: unreachable ({result.stderr.strip() or 'exec failed'}), skipped", file=sys.stderr)
        return False
    return True


def database_url() -> str:
    return os.environ.get("DATABASE_URL", LOCAL_DATABASE_URL)


def ensure_postgres() -> None:
    """Start the compose Postgres (no-op when it is running) and wait until it is healthy."""
    if "DATABASE_URL" in os.environ:
        return  # someone else's database: do not touch compose
    run(["docker", "compose", "up", "-d", "--wait", "postgres"], cwd=ROOT)


def uv(args: list[str], *, env: dict[str, str] | None = None) -> None:
    """`uv run …` in control-plane/."""
    run(["uv", "run", *args], cwd=CP_DIR, env=env)


def alembic(args: list[str]) -> None:
    ensure_postgres()
    uv(["alembic", *args], env={"DATABASE_URL": database_url()})


# --- commands -------------------------------------------------------------


def cmd_proto(_: argparse.Namespace) -> None:
    """Format, lint and regenerate Go + Python code from proto/ (needs buf and protoc plugins)."""
    for args in (["format", "-w"], ["lint"], ["generate"]):
        run(["buf", *args], cwd=ROOT)


def cmd_proto_breaking(_: argparse.Namespace) -> None:
    """Check proto changes for backward compatibility against main."""
    run(["buf", "breaking", "--against", ".git#branch=main"], cwd=ROOT)


def cmd_agent_build(_: argparse.Namespace) -> None:
    """Cross-compile bultd for the nodes into agent/bin/ (local go or Docker)."""
    ver = version()
    env = {"CGO_ENABLED": "0", "GOOS": "linux", "GOARCH": GOARCH}
    go(["build", "-ldflags", f"-X main.version={ver}", "-o", "bin/bultd", "./cmd/bultd"], env=env)
    where = "docker" if use_docker_for_go() else "local go"
    print(f"built {AGENT_BIN.relative_to(ROOT)} {ver} (linux/{GOARCH}, {where})")


def cmd_agent_vet(_: argparse.Namespace) -> None:
    """go vet the agent."""
    go(["vet", "./..."])


def cmd_agent_test(_: argparse.Namespace) -> None:
    """Run agent tests with the race detector (needs cgo: native arch only)."""
    go(["test", "-race", "./..."], env={"CGO_ENABLED": "1"})


def cmd_agent_setup(_: argparse.Namespace) -> None:
    """Create the bultd user on running nodes and write /etc/bult/bultd.env with role, heartbeat and token."""
    ensure_node_tokens()
    ips = node_ips()
    for node in running_nodes():
        print(f"-> {node}")
        node_sh(node, "id bultd >/dev/null 2>&1 || useradd --system --no-create-home "
                      "--shell /usr/sbin/nologin --groups docker bultd")
        if node not in ips:
            print(f"!! {node}: no IP address yet, skipped", file=sys.stderr)
            continue
        role = "builder" if node == BUILDER_NODE else "runner"
        args = [f"--role {role}"]
        if role == "builder":
            args.append(f"--registry {REGISTRY}")
        args += [
            f"--control-plane-url {CONTROL_PLANE_URL}",
            f"--node-name {node}",
            f"--advertise-addr {ips[node]}:{AGENT_PORT}",
        ]
        env_text = f"BULTD_ARGS={' '.join(args)}\nBULTD_NODE_TOKEN={node_token(node)}\n"
        node_put_file(node, "/etc/bult/bultd.env", env_text)
        node_sh(node, "systemctl try-restart bultd || true")  # no-op until the unit is installed
        print(f"   {node}: role {role}, heartbeat to {CONTROL_PLANE_URL} as {ips[node]}:{AGENT_PORT}")


def cmd_agent_deploy(args: argparse.Namespace) -> None:
    """Build, then install bultd + its systemd unit on running nodes and restart it."""
    cmd_agent_build(args)
    for node in running_nodes():
        print(f"-> {node}")
        # multipass transfer drops the exec bit: install with explicit modes.
        run(["multipass", "transfer", str(AGENT_BIN), f"{node}:/tmp/bultd"])
        run(["multipass", "transfer", str(AGENT_UNIT), f"{node}:/tmp/bultd.service"])
        node_sh(node, (
            "pkill -x bultd -u ubuntu 2>/dev/null; "
            "install -m 755 /tmp/bultd /usr/local/bin/bultd && "
            "install -m 644 /tmp/bultd.service /etc/systemd/system/bultd.service && "
            "rm -f /tmp/bultd /tmp/bultd.service && "
            # restart after enable --now: picks up the new binary if it was already running
            "systemctl daemon-reload && systemctl enable --now bultd && systemctl restart bultd"
        ))
        node_sh(node, "systemctl is-active bultd", sudo=False)


def cmd_agent_status(_: argparse.Namespace) -> None:
    """Show bultd service status on running nodes."""
    for node in running_nodes():
        print(f"-> {node}")
        out = node_sh(node, "systemctl status bultd --no-pager --lines=0 || true", sudo=False, capture=True)
        print("\n".join(out.splitlines()[:4]))


def cmd_agent_logs(args: argparse.Namespace) -> None:
    """Show the last journald lines of bultd on one node."""
    node_sh(args.node, f"journalctl -u bultd --no-pager -n {args.lines}", sudo=False)


def cmd_agent_clean(_: argparse.Namespace) -> None:
    """Remove agent build output."""
    shutil.rmtree(AGENT_DIR / "bin", ignore_errors=True)
    print("removed agent/bin")


def cmd_nodes(_: argparse.Namespace) -> None:
    """List node VMs and their IPs."""
    run(["multipass", "list"])


def cmd_up(_: argparse.Namespace) -> None:
    """Start the host stack (registry + control plane) with Docker Compose."""
    ensure_node_tokens()
    run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT)


def cmd_down(_: argparse.Namespace) -> None:
    """Stop the host stack (data volumes are kept)."""
    run(["docker", "compose", "stop"], cwd=ROOT)


def wait_http(url: str, timeout: float) -> bool:
    """Poll a URL until it answers 2xx or the timeout runs out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if 200 <= resp.status < 300:
                    return True
        except OSError:
            pass
        time.sleep(2)
    return False


def cmd_demo_up(_: argparse.Namespace) -> None:
    """Start everything for a demo: node VMs, agents, the host stack; wait until it answers."""
    run(["multipass", "start", *DEMO_NODES])
    for node in DEMO_NODES:
        node_sh(node, "systemctl is-active --quiet bultd || systemctl restart bultd")
        print(f"   {node}: bultd active")
    ensure_node_tokens()
    run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT)
    checks = {"API": "http://localhost:8000/healthz", "dashboard": "http://localhost:3000/"}
    for name, url in checks.items():
        print(f"waiting for the {name}…", flush=True)
        if not wait_http(url, timeout=240):
            sys.exit(f"{name} did not come up: docker compose logs {'api' if name == 'API' else 'web'}")
    print("\nready:")
    print("  dashboard  http://localhost:3000")
    print("  API docs   http://localhost:8000/docs")
    print("  apps       http://<name>.bult.localhost")


def cmd_demo_down(args: argparse.Namespace) -> None:
    """Stop everything after a demo: app replicas, the host stack, node VMs (--wipe: forget all state)."""
    for node in running_nodes():
        if node == BUILDER_NODE or not node_reachable(node):
            continue
        node_sh(node, "ids=$(docker ps -aq --filter label=bult.managed=true); "
                      '[ -z "$ids" ] || docker rm -f $ids')
        print(f"   {node}: app replicas removed")
    if args.wipe:
        run(["docker", "compose", "down"], cwd=ROOT)
        for volume in STATE_VOLUMES:
            run(["docker", "volume", "rm", "-f", volume])
        print("platform state wiped (apps, deploys, routes); registry images kept")
    else:
        run(["docker", "compose", "stop"], cwd=ROOT)
    run(["multipass", "stop", *DEMO_NODES])


def cmd_smoke(args: argparse.Namespace) -> None:
    """Lifecycle check against a running stack (demo-up first); extra args go to scripts/smoke.py."""
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke.py"), *args.smoke_args])
    sys.exit(result.returncode)


# --- control plane --------------------------------------------------------


def cmd_db_up(_: argparse.Namespace) -> None:
    """Start only the compose Postgres and wait until it is healthy."""
    ensure_postgres()


def cmd_migrate(args: argparse.Namespace) -> None:
    """alembic upgrade (default: head) against the local database."""
    alembic(["upgrade", args.revision])


def cmd_makemigrations(args: argparse.Namespace) -> None:
    """alembic revision --autogenerate: migrate to head first, then diff the models against the DB."""
    alembic(["upgrade", "head"])
    alembic(["revision", "--autogenerate", "-m", args.message])
    print("\nread the new file in control-plane/migrations/versions/ before `migrate`")


def cmd_downgrade(args: argparse.Namespace) -> None:
    """alembic downgrade (default: one step back)."""
    alembic(["downgrade", args.revision])


def cmd_db_status(_: argparse.Namespace) -> None:
    """Current revision, the migration history, and whether the models match the DB."""
    alembic(["current"])
    alembic(["history", "--indicate-current"])
    alembic(["check"])


def cmd_db_shell(_: argparse.Namespace) -> None:
    """psql inside the compose Postgres."""
    ensure_postgres()
    run(["docker", "compose", "exec", "postgres", "psql", "-U", "bult", "-d", "bult"], cwd=ROOT)


def cmd_cp_test(args: argparse.Namespace) -> None:
    """Control plane unit tests (pass extra pytest args after --, e.g. -- -k auth)."""
    extra = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    uv(["pytest", "-q", *extra])


def cmd_cp_check(_: argparse.Namespace) -> None:
    """Full check: unit + integration tests, basedpyright, import-linter."""
    ensure_postgres()
    uv(["pytest", "-q"])
    uv(["pytest", "-q", "-m", "integration"])
    run(["uvx", "basedpyright", "app", "tests"], cwd=CP_DIR)
    uv(["lint-imports"])


COMMANDS = {
    "proto": cmd_proto,
    "proto-breaking": cmd_proto_breaking,
    "agent-build": cmd_agent_build,
    "agent-vet": cmd_agent_vet,
    "agent-test": cmd_agent_test,
    "agent-setup": cmd_agent_setup,
    "agent-deploy": cmd_agent_deploy,
    "agent-status": cmd_agent_status,
    "agent-logs": cmd_agent_logs,
    "agent-clean": cmd_agent_clean,
    "nodes": cmd_nodes,
    "up": cmd_up,
    "down": cmd_down,
    "demo-up": cmd_demo_up,
    "demo-down": cmd_demo_down,
    "smoke": cmd_smoke,
    "db-up": cmd_db_up,
    "migrate": cmd_migrate,
    "makemigrations": cmd_makemigrations,
    "downgrade": cmd_downgrade,
    "db-status": cmd_db_status,
    "db-shell": cmd_db_shell,
    "cp-test": cmd_cp_test,
    "cp-check": cmd_cp_check,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="dev.py", description="bult dev tasks")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    for name, func in COMMANDS.items():
        p = sub.add_parser(name, help=(func.__doc__ or "").strip().splitlines()[0])
        if name == "demo-down":
            p.add_argument("--wipe", action="store_true",
                           help="also delete apps, deploys and routes (fresh start)")
        if name == "agent-logs":
            p.add_argument("node", help="node VM name, e.g. bult-builder")
            p.add_argument("-n", "--lines", type=int, default=50)
        if name == "migrate":
            p.add_argument("revision", nargs="?", default="head")
        if name == "downgrade":
            p.add_argument("revision", nargs="?", default="-1")
        if name == "makemigrations":
            p.add_argument("-m", "--message", required=True, help='e.g. "users"')
        if name == "smoke":
            p.add_argument("smoke_args", nargs=argparse.REMAINDER, help="passed to smoke.py, e.g. --keep")
        if name == "cp-test":
            p.add_argument("pytest_args", nargs=argparse.REMAINDER)
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
