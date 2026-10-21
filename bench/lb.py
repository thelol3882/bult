#!/usr/bin/env python3
"""Load-balancing benchmark: round_robin against least_conn through the real ingress.

    python3 bench/lb.py --scenario both            # needs the stack up and app `load` running
    python3 bench/lb.py --help

Per repeat the algorithms alternate (RR, LC, RR, LC, ...): switch the ingress with
`scripts/dev.py lb`, warm up, then run two `hey` streams at once. The fast stream's latency
(p50/p95/p99) is what is compared: how long an unlucky request waits behind a heavy one.
Scenario `slow-replica` adds a third `hey` straight at one replica, bypassing the ingress.
Results: results.json and summary.md (plot them with bench/plot.py). Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEV_PY = ROOT / "scripts" / "dev.py"
SCENARIOS = ("mixed", "slow-replica")
LATENCY_METRICS = ("p50", "p95", "p99", "max")
METRICS = (*LATENCY_METRICS, "throughput", "errors")
# hey's own timeout is 20 s; the slow replica queues requests, so keep it explicit.
HEY_TIMEOUT = 30


def say(text: str = "") -> None:
    print(text, flush=True)


# --- pure parts -------------------------------------------------------------


def percentile(sorted_values: list[float], q: float) -> float:
    """q in [0, 1], linear interpolation between the closest ranks."""
    if not sorted_values:
        raise ValueError("no values")
    pos = (len(sorted_values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


def parse_hey_csv(text: str) -> list[tuple[float, int]]:
    """hey -o csv -> [(latency in seconds, HTTP status)]. Requests that failed at the
    transport level (refused, timed out) are not in hey's CSV at all."""
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        rows.append((float(row["response-time"]), int(row["status-code"])))
    return rows


def summarize(rows: list[tuple[float, int]], seconds: float) -> dict[str, float]:
    """Latency percentiles in ms over the 2xx answers, requests/s, and the non-2xx count."""
    ok = sorted(latency * 1000 for latency, status in rows if 200 <= status < 300)
    errors = len(rows) - len(ok)
    if not ok:
        return {"requests": len(rows), "errors": errors, "throughput": 0.0}
    return {
        "requests": len(rows),
        "errors": errors,
        "throughput": len(ok) / seconds,
        "p50": percentile(ok, 0.50),
        "p95": percentile(ok, 0.95),
        "p99": percentile(ok, 0.99),
        "max": ok[-1],
    }


def run_order(algorithms: list[str], repeats: int) -> list[tuple[int, str]]:
    """(repeat, algorithm) pairs; the algorithms alternate so drift hits both equally."""
    return [(r, a) for r in range(1, repeats + 1) for a in algorithms]


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """scenario -> algorithm -> stream -> metric -> {median, min, max} across the repeats."""
    grouped: dict[tuple[str, str, str, str], list[float]] = {}
    for run in runs:
        for stream in ("fast", "heavy"):
            for metric, value in run[stream].items():
                key = (run["scenario"], run["algorithm"], stream, metric)
                grouped.setdefault(key, []).append(value)
    out: dict[str, Any] = {}
    for (scenario, algorithm, stream, metric), values in grouped.items():
        entry = out.setdefault(scenario, {}).setdefault(algorithm, {}).setdefault(stream, {})
        entry[metric] = {
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "n": len(values),
        }
    return out


def render_summary(aggregates: dict[str, Any], meta: dict[str, Any]) -> str:
    """Markdown: one table per scenario, a row per algorithm (median of the repeats, min-max)."""
    lines = [
        "# Load-balancing benchmark",
        "",
        f"App `{meta['app']}`, {meta['duration']} s per run after {meta['warmup']} s warm-up, "
        f"{meta['repeats']} repeats (median, min-max in brackets). "
        f"Fast stream: {meta['fast_c']} connections x /cpu?ms={meta['fast_ms']}; "
        f"heavy stream: {meta['heavy_c']} x /cpu?ms={meta['heavy_ms']}. Latencies in ms.",
        "",
    ]
    for scenario, algorithms in aggregates.items():
        lines += [f"## {scenario}", ""]
        if scenario == "slow-replica" and meta.get("slow_replica"):
            slow = meta["slow_replica"]
            lines += [f"Slowed replica: #{slow['index']} on {slow['node']} ({slow['address']}).", ""]
        lines += [
            "| algorithm | p50 | p95 | p99 | max | req/s | errors | heavy p50 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for algorithm, streams in algorithms.items():
            fast, heavy = streams["fast"], streams["heavy"]

            def cell(stream: dict[str, Any], metric: str, digits: int = 0) -> str:
                m = stream.get(metric)
                if m is None:
                    return "-"
                return f"{m['median']:.{digits}f} ({m['min']:.{digits}f}-{m['max']:.{digits}f})"

            lines.append(
                f"| {algorithm} | {cell(fast, 'p50')} | {cell(fast, 'p95')} | {cell(fast, 'p99')} "
                f"| {cell(fast, 'max')} | {cell(fast, 'throughput', 1)} | {cell(fast, 'errors')} "
                f"| {cell(heavy, 'p50')} |"
            )
        lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="round_robin vs least_conn through the bult ingress")
    p.add_argument("--app", default="load", help="app name (default: load)")
    p.add_argument("--host-domain", default="bult.localhost", help="apps domain (default: bult.localhost)")
    p.add_argument("--ingress", default="http://localhost", help="ingress address (default: http://localhost)")
    p.add_argument("--api", default="http://localhost:8000", help="API address, for slow-replica")
    p.add_argument("--duration", type=int, default=60, help="seconds per measured run")
    p.add_argument("--warmup", type=int, default=15, help="seconds of discarded warm-up")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--algorithms", default="round_robin,least_conn",
                   help="comma-separated, alternated each repeat")
    p.add_argument("--scenario", choices=(*SCENARIOS, "both"), default="mixed")
    p.add_argument("--fast-c", type=int, default=12)
    p.add_argument("--fast-ms", type=int, default=10)
    p.add_argument("--heavy-c", type=int, default=3)
    p.add_argument("--heavy-ms", type=int, default=300)
    p.add_argument("--slow-c", type=int, default=4, help="slow-replica: direct connections")
    p.add_argument("--slow-ms", type=int, default=300, help="slow-replica: /cpu?ms= of the direct load")
    p.add_argument("--slow-index", type=int, default=0, help="slow-replica: replica index to load")
    p.add_argument("--token-file", help="slow-replica: file with the API token (default: env BULT_TOKEN)")
    p.add_argument("--node-ip", action="append", default=[], metavar="NAME=IP",
                   help="slow-replica: node address (default: from `multipass list`)")
    p.add_argument("--no-switch", action="store_true",
                   help="do not switch the algorithm (it is already set; one algorithm only)")
    p.add_argument("--out", help="results directory (default: bench/results/<timestamp>/)")
    args = p.parse_args(argv)
    args.algorithms = [a.strip() for a in args.algorithms.split(",") if a.strip()]
    args.scenarios = list(SCENARIOS) if args.scenario == "both" else [args.scenario]
    if not args.algorithms:
        p.error("--algorithms is empty")
    if args.no_switch and len(args.algorithms) != 1:
        p.error("--no-switch needs exactly one algorithm (the one currently set)")
    if args.fast_c < 1 or args.heavy_c < 1 or args.repeats < 1 or args.duration < 1:
        p.error("concurrency, repeats and duration must be positive")
    if args.out is None:
        args.out = str(ROOT / "bench" / "results" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    return args


# --- running hey ------------------------------------------------------------


def hey_cmd(url: str, *, host: str | None, c: int, seconds: int, csv_out: bool) -> list[str]:
    cmd = ["hey", "-z", f"{seconds}s", "-c", str(c), "-t", str(HEY_TIMEOUT)]
    if host:
        cmd += ["-host", host]
    if csv_out:
        cmd += ["-o", "csv"]
    return [*cmd, url]


def spawn(cmd: list[str], out: Path | None) -> subprocess.Popen[bytes]:
    """Start hey; its stdout (the CSV) goes to `out`, or nowhere."""
    stdout = open(out, "wb") if out else subprocess.DEVNULL
    return subprocess.Popen(cmd, stdout=stdout, stderr=subprocess.PIPE)


def finish(proc: subprocess.Popen[bytes], name: str) -> None:
    _, err = proc.communicate()
    if proc.stdout:
        proc.stdout.close()
    if proc.returncode != 0 or err.strip():
        say(f"  {name}: hey said: {err.decode(errors='replace').strip()[:300]}")


def load_streams(args: argparse.Namespace, seconds: int, out: Path | None) -> tuple[float, dict[str, list[tuple[float, int]]]]:
    """Run the heavy and fast streams together (plus the direct slow-replica load); wait for all."""
    host = f"{args.app}.{args.host_domain}"
    fast = hey_cmd(f"{args.ingress}/cpu?ms={args.fast_ms}", host=host, c=args.fast_c,
                   seconds=seconds, csv_out=True)
    heavy = hey_cmd(f"{args.ingress}/cpu?ms={args.heavy_ms}", host=host, c=args.heavy_c,
                    seconds=seconds, csv_out=True)
    started = time.monotonic()
    procs = {
        "heavy": spawn(heavy, out / "heavy.csv" if out else None),
        "fast": spawn(fast, out / "fast.csv" if out else None),
    }
    for name, proc in procs.items():
        finish(proc, name)
    elapsed = time.monotonic() - started
    if not out:
        return elapsed, {}
    return elapsed, {n: parse_hey_csv((out / f"{n}.csv").read_text()) for n in ("fast", "heavy")}


# --- environment ------------------------------------------------------------


def switch(algorithm: str) -> None:
    say(f"  switching ingress to {algorithm} ...")
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(DEV_PY), "lb", algorithm],
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"switching to {algorithm} failed:\n{result.stdout}\n{result.stderr}")
    say(f"  switched in {time.monotonic() - started:.0f}s")


def api_get(base: str, path: str, token: str) -> Any:
    request = urllib.request.Request(base.rstrip("/") + path,
                                     headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            return json.load(resp)
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"GET {path}: {e}")


def read_token(args: argparse.Namespace) -> str:
    token = os.environ.get("BULT_TOKEN", "")
    if args.token_file:
        token = Path(args.token_file).read_text().strip()
    if not token:
        sys.exit("slow-replica needs an API token: set BULT_TOKEN or pass --token-file")
    return token


def node_addresses(overrides: list[str]) -> dict[str, str]:
    """Node name -> IP: the --node-ip overrides, else `multipass list`."""
    given = dict(item.split("=", 1) for item in overrides)
    if given:
        return given
    result = subprocess.run(["multipass", "list", "--format", "json"], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("cannot read node addresses from multipass: pass --node-ip NAME=IP")
    return {vm["name"]: vm["ipv4"][0] for vm in json.loads(result.stdout)["list"] if vm.get("ipv4")}


def find_slow_replica(args: argparse.Namespace) -> dict[str, Any]:
    """The running replica to slow down, as {index, node, address}."""
    token = read_token(args)
    page = api_get(args.api, f"/apps/{args.app}/deploys?limit=10", token)
    deploy = next((d for d in page["results"] if d["status"] == "running"), None)
    if deploy is None:
        sys.exit(f"app {args.app} has no running deploy")
    replicas = [r for r in deploy["replicas"] if r["status"] == "running"]
    if len(replicas) < 2:
        sys.exit(f"slow-replica needs at least 2 running replicas, found {len(replicas)}")
    replica = next((r for r in replicas if r["index"] == args.slow_index), None)
    if replica is None:
        sys.exit(f"no running replica with index {args.slow_index}")
    ips = node_addresses(args.node_ip)
    if replica["node"] not in ips:
        sys.exit(f"no address for node {replica['node']}: pass --node-ip {replica['node']}=IP")
    return {"index": replica["index"], "node": replica["node"],
            "address": f"{ips[replica['node']]}:{replica['host_port']}", "replicas": len(replicas)}


def preflight(args: argparse.Namespace) -> None:
    if shutil.which("hey") is None:
        sys.exit("hey is not installed (brew install hey)")
    request = urllib.request.Request(f"{args.ingress}/cpu?ms=1",
                                     headers={"Host": f"{args.app}.{args.host_domain}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            replica = resp.headers.get("X-Replica", "?")
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"app {args.app} does not answer through {args.ingress}: {e}")
    say(f"app {args.app} answers (replica {replica})")


# --- the benchmark ----------------------------------------------------------


def measure(args: argparse.Namespace, scenario: str, algorithm: str, repeat: int,
            slow: dict[str, Any] | None, out: Path) -> dict[str, Any]:
    """One run: warm-up (discarded), then the measured window."""
    run_dir = out / "raw" / f"{scenario}-{algorithm}-{repeat}"
    run_dir.mkdir(parents=True, exist_ok=True)

    direct = None
    if slow:
        # Started before the warm-up and a bit longer than the window: the replica is slow throughout.
        url = f"http://{slow['address']}/cpu?ms={args.slow_ms}"
        direct = spawn(hey_cmd(url, host=None, c=args.slow_c,
                               seconds=args.warmup + args.duration + 5, csv_out=False), None)
    try:
        if args.warmup > 0:
            say(f"  warm-up {args.warmup}s (discarded)")
            load_streams(args, args.warmup, None)
        say(f"  measuring {args.duration}s")
        elapsed, streams = load_streams(args, args.duration, run_dir)
    finally:
        if direct is not None:
            direct.terminate()
            direct.wait()

    record = {
        "scenario": scenario, "algorithm": algorithm, "repeat": repeat,
        "fast": summarize(streams["fast"], elapsed),
        "heavy": summarize(streams["heavy"], elapsed),
    }
    f = record["fast"]
    if "p50" in f:
        say(f"  fast: p50 {f['p50']:.0f} ms, p95 {f['p95']:.0f} ms, p99 {f['p99']:.0f} ms, "
            f"{f['throughput']:.1f} req/s, {f['errors']} errors")
    else:
        say(f"  fast: no successful requests ({f['errors']} errors)")
    return record


def save(out: Path, args: argparse.Namespace, meta: dict[str, Any], runs: list[dict[str, Any]]) -> None:
    aggregates = aggregate(runs)
    (out / "results.json").write_text(json.dumps(
        {"meta": meta, "runs": runs, "aggregates": aggregates}, indent=2))
    (out / "summary.md").write_text(render_summary(aggregates, meta))


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    preflight(args)

    meta: dict[str, Any] = {
        "app": args.app, "duration": args.duration, "warmup": args.warmup, "repeats": args.repeats,
        "algorithms": args.algorithms, "fast_c": args.fast_c, "fast_ms": args.fast_ms,
        "heavy_c": args.heavy_c, "heavy_ms": args.heavy_ms, "started": datetime.now().isoformat(),
    }
    runs: list[dict[str, Any]] = []
    order = run_order(args.algorithms, args.repeats)
    total = len(order) * len(args.scenarios)
    done = 0
    for scenario in args.scenarios:
        slow = None
        if scenario == "slow-replica":
            slow = find_slow_replica(args)
            meta["slow_replica"] = slow
            say(f"\nslow-replica: loading replica #{slow['index']} on {slow['node']} "
                f"({slow['address']}) directly with {args.slow_c} x /cpu?ms={args.slow_ms}")
        for repeat, algorithm in order:
            done += 1
            say(f"\n[{done}/{total}] {scenario} / {algorithm} / repeat {repeat}")
            if not args.no_switch:
                switch(algorithm)
            runs.append(measure(args, scenario, algorithm, repeat, slow, out))
            save(out, args, meta, runs)
    say(f"\ndone: {out}/summary.md and results.json")


if __name__ == "__main__":
    main()
