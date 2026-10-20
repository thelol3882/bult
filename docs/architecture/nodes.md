# Nodes: registration, health and placement

The control plane learns about nodes from the agents themselves, spreads an app's replicas over the ready ones, and sends traffic only to nodes that are alive.

## Heartbeat (push)

Every `bultd` with `--control-plane-url` sends `POST /internal/nodes/heartbeat` every 5 s (the first one right at start):

```json
{"name": "bult-node-1", "address": "192.168.252.6:50051", "role": "runner",
 "version": "v0.4", "capacity": {"cpus": 2, "memory_bytes": 2086961152}}
```

A runner also sends `"replicas": [{"replica_id": "<deploy_id>-r0", "cpu_cores": 0.12, "cpu_limit_pct": 24.0, "mem_bytes": 52428800, "mem_limit_bytes": 268435456}]`, one reading per running replica; the control plane stores them (`metrics.md`). The field is optional, so builders and older agents still work, and a failure to store readings never fails the heartbeat.

`address` is the gRPC address the control plane should dial (`--advertise-addr`); the control plane upserts the `nodes` row and sets `last_seen_at`. A new node appears by starting its agent with a token; nothing is configured on the control plane except the token. The agent logs a failure on the first miss and then once a minute, and stops with its run context on shutdown. Without `--control-plane-url` or `BULTD_NODE_TOKEN` it logs that heartbeats are off and runs as before.

`role` is `builder`, `runner` or `both` (the agent's `--role`).

### Tokens

`BULT_NODE_TOKENS="bult-node-1=<token>,bult-builder=<token>"` (or a JSON object; each token at least 32 characters, `SecretStr`). The agent sends its token as `Authorization: Bearer`; the token must belong to the **name in the request body**, checked with `hmac.compare_digest`. A missing header, an unknown name, a wrong token and another node's token all get the same `401 invalid_node_token`.

Why bound to the name and not one shared secret: a leaked or malicious node would otherwise register under any name and replace another node's address, and then receive its containers, which carry the apps' environment variables. With per-node tokens a compromise is limited to one node's identity. Tokens are never logged (settings validation errors hide their input). mTLS between the control plane and the agents, which would remove tokens altogether, is the production answer and is not done.

`/internal/*` is not for browsers: the dashboard's `/api` proxy refuses it.

## Status

`ready` while `last_seen_at` is within 15 s (`BULT_NODE_TTL_SECONDS`), else `unhealthy`: three missed heartbeats. Status is **derived on read** from `last_seen_at`; nothing stores it, so a crashed control plane cannot leave a stale "ready".

Two thresholds, two costs:

| Reaction | When | Why |
|---|---|---|
| Take the node's replicas out of the upstream | `unhealthy` (~15 s) | cheap and reversible: the replicas keep running, and come back into the upstream when heartbeats return |
| Move its replicas to other nodes | not implemented | expensive and needs certainty: if the node is only partitioned, its containers still run and there are duplicates |

Errors in both directions: calling a live node dead drops capacity and, with a rescheduler, creates duplicates (split brain); calling a dead node alive sends users to a dead upstream. nginx's `proxy_connect_timeout 3s` and, later, `max_fails` cover the second case between two heartbeats.

### Monitor

A loop in the lifespan (every 3 s, `BULT_NODE_MONITOR_INTERVAL`) compares statuses with the previous round. When a known node flips `ready` ↔ `unhealthy` it re-applies the routes (`DeployService.reapply_routes`), so the node's replicas leave or rejoin the upstream. A node that appears for the first time changes nothing. If the callback fails, the same change is looked at again next round.

After a control plane start the monitor waits one TTL before its first round, because the agents have not reported yet and every row looks stale. The startup check renders routes ignoring node health for the same reason; the monitor's first round then refreshes them if some node really is unhealthy. Without this, every restart of the control plane would briefly route nothing.

An app whose replicas are all on unhealthy nodes drops out of the routes (the default server answers `404`); it is not shown as "stopped", which means something else.

## Directory of agents

`AgentClients` no longer holds channels created at startup. It asks a `Directory` (the nodes domain's facade) for the address of the builder or of a runner on every call and keeps one channel per node, created on first use, replaced when the address changes (the old one gets 5 s to finish its calls) and closed at shutdown.

- The builder is a **ready** node with role `builder` or `both`; no ready builder means `UNAVAILABLE` ("builder unavailable, try again" for the user).
- Runners are all known nodes with role `runner` or `both`, each with a ready flag. An unhealthy runner is still addressable: `RemoveReplica` and listing are tried and may fail.
- The directory reads the `nodes` table through a 1 s cache (every RPC asks), dropped by any heartbeat handled in the same process.

**Static fallback.** `BULT_BUILDER` and `BULT_RUNNERS` still exist. They are used **per role, only while no node of that role has registered**: registered nodes win. So an old setup without heartbeats keeps working, and once the first runner reports, the static runner list is ignored (a configured runner that never reports disappears). Tests use the fallback.

## Replicas and the scheduler

`replicas` (id `{deploy_id}-r{i}`, `deploy_id` FK cascade, `index`, `node`, `host_port`, `status`) records where a deploy runs. Rows stay after a replica is retired (`removed`), so a deploy's history still shows where it ran. `deploys.node/host_port` were replaced by these rows (the migration copies them as replica 0) and `deploys.ran` ("reached running", what makes a deploy restorable) and `desired_replicas`.

Placement, one replica at a time: among the ready runners, the one with the **fewest replicas of this deploy**, then the fewest replicas in total, then the lowest name. Several replicas per node are allowed (3 replicas on 2 nodes: 2 + 1). Only the deploy's own replicas count for the first key: in a blue-green redeploy the old replicas are about to go, and counting them would push the new ones off their nodes. If a node fails `RunReplica`, the replica is tried on the next best node and the failed one is skipped for the rest of that call.

## Scaling

`PUT /apps/{name}/replicas {"replicas": N}` (N in 0..5, owner only). It refuses while a deploy is in progress (409).

| State | Effect |
|---|---|
| N = 0 | same as stop |
| running, N more | place the missing replicas in the lowest free indices, update the routes |
| running, N fewer | retire the highest indices, update the routes **first**, then remove the containers |
| not running | start from the last image that ran (`409 nothing_to_start` if none) with N replicas |

No build happens in any case. Adding replicas fails with `503 no_node_available` when none started; some starting is fine (`ready/desired`). Scaling to the current count tops up missing replicas. `/stop` and `/start` still work; `/start` uses the app's replicas, at least 1, and a stop forgets the count (`replicas = 0`).

## Why push, and how it scales

Pull (the control plane polls every node's `ListReplicas`/health) needs no token or registration and is simpler on three nodes: the control plane already knows the addresses and nothing runs on a node except the agent. Push was chosen because adding a node is just starting its agent with a token, the control plane holds no node list to keep in sync, and the load is one tiny write per node per 5 s.

At hundreds of nodes the heartbeat becomes the largest write stream into the database, and Kubernetes solves exactly this: each kubelet renews a small `Lease` object (about every 10 s; a cheap separate object, not the whole Node status), and the node controller marks a node `Unknown` after a grace period of tens of seconds. The same step here would be keeping `last_seen_at` outside the `nodes` table (a lease row or an in-memory/Redis TTL key) and writing the rest of the node data only when it changes. Push also works for nodes behind NAT, where pull cannot reach them. The cost of push is the token per node and agents that must reach the control plane; the cost of pull is that the control plane must reach every node and does the work of probing.

## Dev setup (Multipass)

- The API must be reachable from the VMs: `control-plane/compose.yaml` publishes it on `127.0.0.1:8000` and on the Multipass bridge `192.168.252.1:8000`, next to the registry on `:5050`. The bridge address exists while the VMs are running, so start them first (`demo-up` does); another address: `BULT_API_BRIDGE_IP=... docker compose up`. The VMs reach it as `BULT_CONTROL_PLANE_URL` (default `http://192.168.252.1:8000`).
- Tokens are derived, not stored per node: `scripts/dev.py` keeps a random secret in the gitignored `.bult/node-secret` and uses `HMAC-SHA256(secret, "bult-node:<name>")` as the token of `<name>`. `ensure_node_tokens()` (run by `up`, `demo-up` and `agent-setup`) writes `BULT_NODE_TOKENS=...` for every node in `BULT_NODES` into `.bult/node-tokens.env`, which `control-plane/compose.yaml` reads as an optional `env_file`. `agent-setup` computes the same token and installs `/etc/bult/bultd.env` (mode 600, root) on each running node with `BULTD_NODE_TOKEN`, `--control-plane-url`, `--node-name` (the VM name) and `--advertise-addr` (the VM's IP, port 50051) next to the role flags, then restarts `bultd`. Same secret, same tokens: nothing to keep in sync by hand, and nothing secret in git or on a command line.
- Production would use a real secret store and rotate tokens; the derivation is a dev convenience.
