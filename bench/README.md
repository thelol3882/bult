# bench: round-robin against least_conn

`lb.py` measures what the ingress balancing algorithm does to latency, through the real ingress
and real replicas. Two `hey` streams run at the same time against app `load`
(`examples/fastapi-load`): a heavy one (3 connections, `/cpu?ms=300`) and a fast one
(12 connections, `/cpu?ms=10`). The fast stream's p50/p95/p99 is what is compared: how long an
unlucky fast request waits behind a heavy one. Averages are not used: they hide the tail.

- **mixed**: the three replicas are equal. Round-robin ignores what each replica is busy with;
  least_conn sends the next request to the replica with the fewest open ones.
- **slow-replica**: one replica is also loaded directly (a third `hey`, bypassing the ingress),
  so it is slow. Round-robin still gives it a third of the traffic; least_conn steers away.

Each repeat alternates the algorithms (RR, LC, RR, LC, ...), switches the ingress, warms up
(discarded), then measures. Results are the median of the repeats, with min-max.

## Prerequisites

- Stack up (`python3 scripts/dev.py demo-up`), nodes registered and healthy.
- App `load` deployed from `examples/fastapi-load` with **3 replicas** and running.
- `hey` on the host (`brew install hey`).
- For `slow-replica`: an API token of the app's owner, in `BULT_TOKEN` (or `--token-file`).
  The script never prints it:

  ```
  export BULT_TOKEN=$(curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
      -d '{"email": "...", "password": "..."}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
  ```

  Node addresses come
  from `multipass list`; without it pass `--node-ip bult-node-1=192.168.252.6`.
- Close other heavy programs; the ingress, the load generator and the VMs share this machine.

## Run

```
python3 bench/lb.py --scenario mixed          # ~7 min: 6 runs x (15 + 60 s) + 6 switches
python3 bench/lb.py --scenario slow-replica
python3 bench/lb.py --scenario both           # ~14 min
python3 bench/lb.py --scenario both --duration 20 --warmup 5 --repeats 1   # quick look
```

Other options: `--app`, `--host-domain`, `--ingress`, `--api`, `--algorithms`,
`--fast-c/--fast-ms`, `--heavy-c/--heavy-ms`, `--slow-c/--slow-ms/--slow-index`, `--out`.
Run `python3 bench/lb.py --help` for all of them.

The algorithm is switched by `python3 scripts/dev.py lb <round_robin|least_conn|ip_hash>`: it
writes `.bult/lb.env`, recreates the `api` container (BULT_LB_ALGORITHM is read at start; the API
re-renders the routes on start) and waits until the ingress runs a generation with the new
directive (about 5-15 s). It leaves the stack on the last algorithm; run
`dev.py lb round_robin` afterwards to go back to the default.

Plots (matplotlib is fetched on the fly):

```
uv run --with matplotlib python3 bench/plot.py bench/results/<run>/
uv run --with matplotlib python3 bench/plot.py bench/results/<run>/ --copy-to docs/report/figures/
```

Tests of the script's pure parts: `python3 -m unittest discover -s bench`.

## Output (`bench/results/<timestamp>/`, gitignored)

- `summary.md`: a table per scenario, a row per algorithm: median (min-max) of the repeats.
- `results.json`: every run plus the aggregates.
- `raw/<scenario>-<algorithm>-<repeat>/{fast,heavy}.csv`: hey's per-request data.
- `lb-<scenario>.png`: bars of p50/p95/p99, whiskers min-max.

Expectation: p50 about equal; least_conn lower at p95/p99, clearly so with the slow replica.
If the whiskers of the two algorithms overlap, the difference is not established: repeat or lengthen.

## Caveats

- Everything runs on one laptop: the load generator, the ingress container and the VMs share
  CPU. The numbers compare algorithms under the same conditions, not the platform's capacity.
- The `errors` column counts non-2xx answers only; hey's CSV omits requests that failed to
  connect or timed out. Check hey's output (printed if it complains) and the ingress logs.
- The replica distribution (`X-Replica`) is not measured: hey does not record response headers.
- `/cpu` busy-loops a thread of one replica: with a 2-CPU node, replicas on the same node
  also compete with each other.
