# Replica metrics: CPU and memory

Pipeline: `docker stats` on the node -> the node's heartbeat -> Postgres -> `GET /apps/{name}/metrics` -> dashboard.

```
bultd (runner)            control plane                         dashboard
  Docker stats  --5 s-->  POST /internal/nodes/heartbeat        Metrics tab
  (per replica)           resolve replica -> app, bulk insert   polls every 5 s
                          replica_metrics  <-- retention loop   GET /apps/{name}/metrics
```

## Agent

Every beat, `internal/metrics.Collector` lists the running containers with the label `bult.managed=true` and reads each one's stats **in parallel** (at most 8 at a time). The Docker daemon is asked for a previous sample too (`IncludePreviousSample`), so one call takes about a second and carries both readings needed for a rate. The whole collection has a 3 s timeout, shorter than the 5 s interval: what could not be read in time is left out, the heartbeat still goes (liveness matters more than a chart). A container that fails, is gone or is not running is skipped, never fatal.

**CPU.** The counters are cumulative CPU time since the container started, so a rate needs two readings:

```
cores = (cpu_total - precpu_total) / (system_cpu - presystem_cpu) * online_cpus
cpu_limit_pct = cores / (NanoCPUs / 1e9) * 100        # no limit: online_cpus is the ceiling
```

`cpu_limit_pct` is relative to the replica's own limit: 100 means it is at its ceiling and the kernel throttles it. A reading without a previous sample, with a zero system delta or with a counter that went backwards is skipped, not reported as 0.

**Memory.** `mem_bytes = usage - inactive_file` (cgroup v2 key `inactive_file`, v1 `total_inactive_file`), the number `docker stats` shows: the page cache is reclaimable and would otherwise make every app that reads files look like it leaks. `mem_limit_bytes` is the cgroup limit (the host's memory when none is set).

Payload, one entry per running replica (omitted for builders and when nothing was read):

```json
"replicas": [{"replica_id": "3f9c...-r0", "cpu_cores": 0.118, "cpu_limit_pct": 23.6,
              "mem_bytes": 52428800, "mem_limit_bytes": 268435456}]
```

Not sent: whether a replica was OOM-killed. It is visible as an exited replica (exit code 137) in the API already.

## Control plane

- **Storing.** The nodes router authenticates the heartbeat, records liveness, then hands the readings to a sink supplied by `main` (nodes know nothing about metrics). The metrics service resolves the replica ids through the deploys facade (`replica_owners`: running replicas only) and keeps a reading only if the replica **runs on the node that reported it**; unknown ids are ignored. One short UoW, one bulk insert. An exception in the sink is logged and the heartbeat still answers 204.
- **Table** `replica_metrics(id, replica_id, app_name, node, ts, cpu_cores, cpu_limit_pct, mem_bytes, mem_limit_bytes)`, indexes `(app_name, ts)` for the chart and `(replica_id, ts)`. No foreign key: replica rows outlive their containers, and history of a retired replica is still wanted. `app_name` is denormalized for the same reason. Deleting an app deletes its samples (`AppDeleted`), so a new app with that name starts empty.
- **Retention.** A loop in the lifespan deletes samples older than `BULT_METRICS_RETENTION_HOURS` (24) every `BULT_METRICS_RETENTION_INTERVAL` seconds (300), 5000 rows per statement, until a batch comes back short. Size: 5 s * N replicas * 24 h = 17 280 rows per replica per day (about 1.5 MB with indexes), so a few hundred thousand rows on the dev stand. The purge filters on `ts` alone and scans the table; at larger sizes it would want a `ts` index or partitions dropped by day.
- **API.** `GET /apps/{name}/metrics?period=15m|1h|24h`, owner only (403 for another user's app, 422 for another period). Samples are averaged **in SQL** with `date_bin(bucket, ts, origin)` per replica; the bucket is `max(5 s, ceil(period / 299))`, i.e. 5 s, 13 s and 289 s, which is at most 300 points per series (one bucket is spared because the window start is not aligned to a bucket). Series: `{replica_id, index, node, points: [[ts, cpu_limit_pct, mem_bytes], ...]}`; `index` is read from the id (`<deploy_id>-r<index>`). During a blue-green redeploy the old and the new replica of the same index are separate series. Summary: totals of the newest reading of each replica seen in the last 15 s (`cpu_cores`, `mem_bytes`, `mem_limit_bytes`), `ready_replicas` (running replicas of the newest running deploy on ready nodes) and `desired_replicas` (the app's setting).

## Dashboard

Metrics tab on the app page: three tiles, a CPU chart (% of the limit, a guide line at 100) and a memory chart, one line per replica labelled `r0 · node-1`, a period switcher, polling every 5 s while the tab is visible and the page is in focus. The legend shows the newest value of each line, which doubles as the table view; colours are chosen by replica index (a validated categorical palette, light and dark steps), so a replica keeps its colour across redeploys, and an older deploy's replica still inside the period is drawn dashed. Charts: `@mantine/charts` (recharts), because the dashboard is Mantine already and it brings tooltips and theming without a second design system.

## Why this way

| Choice | Alternative | Why not |
|---|---|---|
| Metrics ride the heartbeat | control plane polls `stats` per request or per node | no new connection, the load grows with nodes, not with viewers; history needs a collector anyway |
| % of the replica's limit | absolute cores | "is it tight?" is the question; 0.4 cores is full for a 0.5-core limit and idle for 4 |
| Postgres, 24 h | a TSDB | one store less on a three-node stand; the data is small |
| Downsample in SQL | send raw points, thin out in the browser | 17 280 points per replica per day would cross the wire on every poll |

## How it would scale

- A time-series store: TimescaleDB (a Postgres extension, so queries and migrations stay the same, with hypertables, retention policies and continuous aggregates) or Prometheus/VictoriaMetrics with the agent as an exporter.
- Pull for metrics is the norm there: Prometheus scrapes every node, which gives service discovery, staleness handling and a query language; the cost is the control plane (or Prometheus) reaching every node.
- Downsampling at write time: keep raw 5 s for a few hours, 1-minute averages for weeks, hourly for months, instead of one resolution for everything.
- Agents batch and compress samples, and skip unchanged values, once the heartbeat becomes the largest write stream (the same argument as `last_seen_at` in `nodes.md`).
