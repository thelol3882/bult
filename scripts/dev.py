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
    BULT_GOARCH        node CPU architecture        (default: this machine's — Multipass VMs match the host)
    BULT_GO_DOCKER=1   build/test the agent in Docker even if `go` is installed
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"
AGENT_BIN = AGENT_DIR / "bin" / "bultd"
AGENT_UNIT = ROOT / "deploy" / "systemd" / "bultd.service"

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
REGISTRY = os.environ.get("BULT_REGISTRY", "192.168.252.1:5050")
GOARCH = os.environ.get("BULT_GOARCH") or host_goarch()


# --- helpers --------------------------------------------------------------


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True, capture: bool = False) -> str:
    """Run a command, echo it, stop the script on failure."""
    print("$", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture)
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


def node_sh(node: str, script: str, *, sudo: bool = True, capture: bool = False) -> str:
    """Run a shell snippet on a node (always /bin/sh on the VM, whatever the host shell is)."""
    cmd = ["multipass", "exec", node, "--"]
    if sudo:
        cmd.append("sudo")
    return run([*cmd, "sh", "-c", script], capture=capture)


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
    """Create the bultd user on running nodes and the builder's /etc/bult/bultd.env (idempotent)."""
    for node in running_nodes():
        print(f"-> {node}")
        node_sh(node, "id bultd >/dev/null 2>&1 || useradd --system --no-create-home "
                      "--shell /usr/sbin/nologin --groups docker bultd")
        if node == BUILDER_NODE:
            env_line = f"BULTD_ARGS=--role builder --registry {REGISTRY}"
            node_sh(node, f"mkdir -p /etc/bult && printf '%s\\n' '{env_line}' > /etc/bult/bultd.env")
            print(f"   {node}: role builder, registry {REGISTRY}")


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
    run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT)


def cmd_down(_: argparse.Namespace) -> None:
    """Stop the host stack (data volumes are kept)."""
    run(["docker", "compose", "stop"], cwd=ROOT)


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
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="dev.py", description="bult dev tasks")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    for name, func in COMMANDS.items():
        p = sub.add_parser(name, help=(func.__doc__ or "").strip().splitlines()[0])
        if name == "agent-logs":
            p.add_argument("node", help="node VM name, e.g. bult-builder")
            p.add_argument("-n", "--lines", type=int, default=50)
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
