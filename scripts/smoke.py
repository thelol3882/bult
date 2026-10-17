#!/usr/bin/env python3
"""bult smoke test: the whole app lifecycle against a running stack.

    python3 scripts/dev.py demo-up        # VMs, agents, API, dashboard, ingress
    python3 scripts/smoke.py              # or: python3 scripts/dev.py smoke

Registers a throwaway user, deploys examples/fastapi-html and walks through
redeploy, env, logs, stop/start, rollback, cancel and delete. Every step
prints PASS or FAIL; the first failure stops the run (the later steps depend
on it), the app is still deleted, and the exit code is 1. The dashboard
shows the same app while it runs. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

ACTIVE = {"queued", "building", "starting"}


class Failure(Exception):
    """A step did not get what it expected."""


def say(text: str = "") -> None:
    print(text, flush=True)


class Api:
    """Just enough HTTP client for the bult API (JSON, Bearer token)."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token = ""

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if data else {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except OSError as e:
            raise Failure(f"{method} {path}: cannot reach the API ({e})") from None
        return status, (json.loads(raw) if raw else None)

    def expect(self, want: int, method: str, path: str, body: Any = None) -> Any:
        status, payload = self.call(method, path, body)
        if status != want:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise Failure(f"{method} {path}: expected {want}, got {status} ({detail})")
        return payload


def fetch(url: str, host: str) -> tuple[int, str]:
    """GET url with a Host header (the ingress routes by it); returns (status, body)."""
    request = urllib.request.Request(url, headers={"Host": host})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except OSError:
        return 0, ""


def wait_for(what: str, check: Callable[[], Any], timeout: float, every: float = 2.0) -> Any:
    """Call check() until it returns something truthy."""
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            raise Failure(f"timed out after {timeout:.0f}s waiting for {what}")
        time.sleep(every)


class Smoke:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.api = Api(args.api)
        self.name = f"smoke-{secrets.token_hex(3)}"
        self.host = f"{self.name}.{args.base_domain}"
        self.first = ""  # id of the first deploy
        self.second = ""
        self.secret = secrets.token_urlsafe(18)

    # --- helpers

    def deploy(self, deploy_id: str) -> dict:
        return self.api.expect(200, "GET", f"/apps/{self.name}/deploys/{deploy_id}")

    def wait_deploy(self, deploy_id: str, want: str, timeout: float) -> dict:
        """Poll a deploy until it reaches `want`; any other final status is a failure."""
        seen: list[str] = []

        def check() -> dict | None:
            d = self.deploy(deploy_id)
            if not seen or seen[-1] != d["status"]:
                seen.append(d["status"])
                say(f"      {deploy_id[:8]}: {d['status']}")
            if d["status"] == want:
                return d
            if d["status"] not in ACTIVE:
                raise Failure(f"deploy ended as {d['status']}: {d.get('error') or 'no error text'}")
            return None

        return wait_for(f"deploy {deploy_id[:8]} to become {want}", check, timeout)

    def site(self) -> tuple[int, str]:
        return fetch(self.args.ingress, self.host)

    def expect_site(self, want: int, timeout: float = 30) -> str:
        last: list[tuple[int, str]] = []

        def check() -> bool:
            last[:] = [self.site()]
            return last[0][0] == want

        try:
            wait_for(f"{self.host} to answer {want}", check, timeout, every=1.0)
        except Failure:
            raise Failure(f"{self.host} answered {last[0][0]}, expected {want}") from None
        return last[0][1]

    # --- steps

    def register(self) -> None:
        email = f"{self.name}@example.com"
        password = secrets.token_urlsafe(24)  # never printed
        self.api.expect(201, "POST", "/auth/register", {"email": email, "password": password})
        token = self.api.expect(200, "POST", "/auth/login", {"email": email, "password": password})
        self.api.token = token["access_token"]

    def create_app(self) -> None:
        app = self.api.expect(201, "POST", "/apps", {
            "name": self.name, "preset": "fastapi", "repo_url": self.args.repo,
            "branch": self.args.branch, "subdir": self.args.subdir,
        })
        if app["replicas"] != 1:
            raise Failure(f"new app has replicas={app['replicas']}, expected 1")

    def first_deploy(self) -> None:
        self.first = self.api.expect(202, "POST", f"/apps/{self.name}/deploys")["id"]
        self.wait_deploy(self.first, "running", self.args.deploy_timeout)

    def check_site(self) -> None:
        self.expect_site(200)

    def redeploy(self) -> None:
        self.second = self.api.expect(202, "POST", f"/apps/{self.name}/deploys")["id"]
        self.wait_deploy(self.second, "running", self.args.deploy_timeout)
        wait_for("the first deploy to become superseded",
                 lambda: self.deploy(self.first)["status"] == "superseded", 30)
        self.expect_site(200)

    def set_env(self) -> None:
        put = self.api.expect(200, "PUT", f"/apps/{self.name}/env", {"env": {"SMOKE_SECRET": self.secret}})
        got = self.api.expect(200, "GET", f"/apps/{self.name}")
        if "SMOKE_SECRET" not in got["env_keys"]:
            raise Failure("the variable name is not listed in env_keys")
        for body in (put, got):
            if self.secret in json.dumps(body):
                raise Failure("the secret value is readable through the API")

    def logs(self) -> None:
        self.site()  # makes sure the app has written something

        def lines() -> bool:
            return bool(self.api.expect(200, "GET", f"/apps/{self.name}/logs")["lines"])

        wait_for("log lines", lines, 30)

    def stop(self) -> None:
        self.api.expect(204, "POST", f"/apps/{self.name}/stop")
        self.expect_site(503)

    def start(self) -> None:
        started = self.api.expect(202, "POST", f"/apps/{self.name}/start")
        if not started["source_deploy_id"]:
            raise Failure("start did not reuse an image (no source_deploy_id)")
        if started["status"] in ("queued", "building"):
            raise Failure(f"start went through {started['status']}: it must not build")
        self.wait_deploy(started["id"], "running", 120)
        self.expect_site(200)

    def rollback(self) -> None:
        rolled = self.api.expect(202, "POST", f"/apps/{self.name}/deploys/{self.first}/rollback")
        if rolled["source_deploy_id"] != self.first:
            raise Failure("the rollback deploy does not point at the first deploy")
        self.wait_deploy(rolled["id"], "running", 120)
        self.expect_site(200)

    def cancel(self) -> None:
        deploy_id = self.api.expect(202, "POST", f"/apps/{self.name}/deploys")["id"]
        for _ in range(10):  # 409 "just being picked up": try again in a moment
            status, payload = self.api.call("POST", f"/apps/{self.name}/deploys/{deploy_id}/cancel")
            if status == 202:
                break
            if status != 409 or payload.get("code") != "deploy_not_cancellable":
                raise Failure(f"cancel answered {status}: {payload}")
            time.sleep(1)
        else:
            raise Failure("cancel kept answering 409")
        self.wait_deploy(deploy_id, "cancelled", 120)
        status = self.api.expect(200, "GET", f"/apps/{self.name}/deploys/{deploy_id}")["status"]
        if status != "cancelled":
            raise Failure(f"final status is {status}")
        # a cancelled deploy frees the app for the next one, and the old version keeps serving
        self.expect_site(200)

    def delete(self) -> None:
        self.api.expect(204, "DELETE", f"/apps/{self.name}")
        self.api.expect(404, "GET", f"/apps/{self.name}")

    # --- run

    def run(self) -> bool:
        steps: list[tuple[str, Callable[[], None]]] = [
            ("register a throwaway user", self.register),
            (f"create app {self.name}", self.create_app),
            ("deploy and wait for running", self.first_deploy),
            (f"{self.host} answers 200", self.check_site),
            ("redeploy: old deploy superseded, site still up", self.redeploy),
            ("set env: value never readable", self.set_env),
            ("logs are not empty", self.logs),
            ("stop: 503 stopped page", self.stop),
            ("start: running again without a build", self.start),
            ("rollback to the first deploy", self.rollback),
            ("cancel a fresh deploy", self.cancel),
        ]
        ok = True
        try:
            for number, (title, step) in enumerate(steps, start=1):
                say(f"[{number:>2}/{len(steps) + 1}] {title}")
                started = time.monotonic()
                try:
                    step()
                except Failure as e:
                    say(f"      FAIL ({e})")
                    ok = False
                    break
                say(f"      PASS ({time.monotonic() - started:.0f}s)")
        finally:
            say(f"[{len(steps) + 1:>2}/{len(steps) + 1}] delete the app")
            if self.args.keep:
                say(f"      SKIP (--keep): app {self.name} is left at {self.host}")
            elif not self.api.token:
                say("      SKIP (nothing was created)")
            else:
                try:
                    self.delete()
                    say("      PASS")
                except Failure as e:
                    say(f"      FAIL ({e})")
                    ok = False
        say("\nPASS: all steps" if ok else "\nFAIL: see above")
        return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="bult smoke test against a running stack")
    parser.add_argument("--api", default="http://localhost:8000", help="API address (default: %(default)s)")
    parser.add_argument("--base-domain", default="bult.localhost", help="apps live at <name>.<domain> (default: %(default)s)")
    parser.add_argument("--ingress", default="http://localhost", help="where the ingress listens (default: %(default)s)")
    parser.add_argument("--repo", default="https://github.com/thelol3882/bult", help="repository to deploy (default: %(default)s)")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--subdir", default="examples/fastapi-html")
    parser.add_argument("--deploy-timeout", type=float, default=900, help="seconds to wait for a build (default: %(default)s)")
    parser.add_argument("--keep", action="store_true", help="do not delete the app at the end")
    args = parser.parse_args()
    sys.exit(0 if Smoke(args).run() else 1)


if __name__ == "__main__":
    main()
