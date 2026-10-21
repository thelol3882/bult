# Replica health

A replica is only useful while it works. The platform used to know whether a **node** was alive; now it also knows whether each **container** is, takes a broken one out of the upstream at once, and replaces it.

## Signal flow

```
bultd (node)                              control plane
  Docker events (die/oom/start) ─┐
  full list every 30 s ──────────┼─> replica state ──┐
  health probe every 10 s ───────┘    (in memory)    │ heartbeat, every 5 s
                                                     └──────────────> replica rows (Postgres)
                                                                          │ wakes
                                          routes <── reconciler (every 5 s, or at once) ──> RunReplica / RemoveReplica
                                        (serving only)
```

**Agent.** It keeps the state of every `bult.managed` container: `running`, `exited` or `oom`, exit code, `finished_at`. Docker events (`die`, `oom`, `start`, `destroy`) are only a trigger: the agent re-inspects the container. Events can be missed (a dropped stream, a restart of the agent), so every 30 s the agent lists everything again, the same list-and-watch pair Kubernetes uses; both feed one merge function. The health probe runs on the agent next to the container (like the kubelet): every 10 s, timeout 2 s, **unhealthy after 3 consecutive failures, healthy again after 1 success**. The default probe is a TCP connect to the replica's host port; with a health path it is `GET <path>` where 2xx/3xx is healthy (redirects are not followed). The path reaches the agent as the reserved variable `BULT_HEALTH_PATH` in the `RunReplica` env (users cannot set `BULT_*` variables); the agent removes it from the container's environment, validates it and keeps it as the label `bult.health_path`, so it survives an agent restart. A path changed in the app's settings applies to replicas started afterwards.

**Heartbeat.** Each entry of `replicas` carries both metrics and state, and exited containers are included, so the control plane learns about deaths:

```json
{"replica_id": "3f9c-r0", "state": "running", "oom_killed": false, "healthy": true,
 "cpu_cores": 0.118, "cpu_limit_pct": 23.6, "mem_bytes": 52428800, "mem_limit_bytes": 268435456}
{"replica_id": "3f9c-r1", "state": "exited", "exit_code": 1, "oom_killed": false, "healthy": false,
 "finished_at": "2026-10-21T09:30:05Z"}
```

`reports_replicas: true` at the top level says the list is complete (the agent finished a full list), so a replica missing from it is gone. An older agent sends metrics only; the control plane then changes nothing about health.

**Control plane.** The heartbeat handler only writes the replica rows (`state`, `healthy`, `exit_code`, `unhealthy_since`, the death history) and, if the set of serving replicas changed, wakes the reconciler. Rows are updated only while they are still placed on the reporting node, and an `exited` report older than the row's current container (`finished_at < placed_at`) is ignored, so a stale list cannot kill a fresh replacement.

States of a replica row: `running` (serving when also healthy), `exited`, `oom`, `lost` (its node is dead), `crashloop`. In the API a running replica that fails its probe, or whose node stopped reporting, is `unhealthy`. **Routes contain only replicas that run and are healthy on ready nodes**; `ready_replicas` counts the same set. An app with no such replica gets the default server's 404, the same as when all its nodes are unhealthy.

## Reconciler

One loop in the API process (single instance), every 5 s and whenever a heartbeat wakes it; it waits one node TTL after a start, because every node looks silent until the agents have reported. For each running deploy's replica rows:

1. **Node dead** (silent 60 s, `BULT_NODE_DEAD_SECONDS`): the row becomes `lost`. No failure is counted and no backoff applies (not the app's fault); it is replaced at once on a ready node.
2. **Hung app**: unhealthy continuously for 60 s (the agent needs 30 s of failed probes to say so first) counts as a death, reason "health check failed". Slow starts and short stalls recover by themselves and are not punished.
3. **Death** (container exited, OOM-killed, gone from a complete report): the row gets a `retry_at` and the app's last 20 log lines are fetched while the container still exists (`tail_pending`). Backoff per slot: **10 s, 20 s, 40 s ... up to 5 min** (`backoff(n)`, n = deaths in the window).
4. **Replacement** after the backoff: the container with the same name is removed, then the same slot (replica id) is started again, **on the same node if it is ready and the old container could be removed, otherwise on another ready node**. The row is moved with a guarded update (`rehome`): if the slot was retired or replaced meanwhile, the container just started is removed again. A replacement that cannot start is retried after 15 s. Replacements run as tasks, so a slow image pull does not stall the loop. The slot's id is reused, so the death history stays with the slot; it only replaces dead rows (slots the deploy never started are not topped up; a scale does that).
5. **Crash loop**: **5 deaths of one slot within 10 minutes** make it `crashloop`; replacements stop until the next deploy, scale or start. The dead container is kept on the node, and the UI shows the exit code and the log tail (the app's own output; whatever the app prints is its own business). A scale resets crash-looping slots of the running deploy to a fresh start.
6. **Strays (GC on every heartbeat)**: a container the node reports that no live deploy wants (its deploy is over, or the row now lives on another node, as after a node came back from the dead) is removed once it has been seen for 15 s. The grace exists because a replica's row is written just after its container starts. The database is the truth; replicas of deploys still in flight are never touched.
7. Routes are re-rendered when the serving set changed.

Unhealthy-but-running replicas **are** replaced (after the grace above): a process that stays hung does not recover, and the capacity is lost until someone intervenes.

## Why `restart: no` and one restarter

Docker can restart containers itself (`--restart`), but then two controllers fight: after a node reboot Docker would revive replicas the control plane already replaced or removed, and a restarting container hides crash loops from the platform. So agents only report and the control plane alone decides. Kubernetes has two levels: the kubelet restarts a crashed container in place (with the same crash-loop backoff), and a controller reschedules pods when the node itself dies. bult has one: the control plane replaces in place when the node is alive and elsewhere when it is not. The price is latency (heartbeat plus a reconcile round, seconds) and a control plane that must be up to restart anything; at a few nodes a single decision maker is simpler and its state is visible in one table.

## Scale-down

Victims in order: replicas that do not serve (dead, hung, crash-looping, on a node that is not ready); then, one at a time, from the node that holds the most replicas of the app (so the rest stays spread); on a tie the newest.

## Limits

- Probes run on the node: a network path problem between the ingress and the node is invisible to them (nginx's `max_fails` covers that).
- A control plane restart delays replacements by one node TTL.
- The log tail is read when a death is first handled; a container removed before that has none.
- Health path changes apply to new replicas only.
