# NodeAgent API — design notes

> Design in words, agreed on 2026-10-04. The `.proto` contract in `proto/bult/agent/v1/` follows this document.

## Principles

1. **The agent is the source of truth for what happens on its node.** The control plane stores intent and metadata; the agent knows the facts (is a build running, what is in its log). Same as kubelet: `kubectl logs` is served from the node, not from etcd.
2. **A deploy's lifetime is not tied to a connection.** Neither a closed browser tab nor a control-plane restart kills a build. Only an explicit `CancelDeploy` does.
3. **Reconciliation.** On startup and periodically, the control plane compares its records (`building`, replicas) with what agents report, and fixes "zombie" states.
4. **Failure is a gRPC status**, not "a successful call carrying an error message". The status code tells the client what to do next.
5. **All IDs come from the control plane.** The agent is an executor and never invents identifiers (see [Idempotency](#ids-and-idempotency)).

## Roles: build once, run many

- An image is built **once**, on a dedicated build node (`bult-builder`), and pushed to a self-hosted registry. Worker nodes only pull and run.
- Same `bultd` binary everywhere; the role comes from config: `builder` or `runner`.
- Why not build on worker nodes:
  - **noisy neighbor** — a build (Next.js/TypeScript: gigabytes of RAM) starves co-located apps, up to OOM kills;
  - **reproducibility** — two builds of the same commit can produce different images (unpinned dependencies), so replicas of "the same release" would run different code;
  - **rollback** — the image lives centrally; rolling back means running the previous image on any node, no rebuild;
  - **security** — a build executes untrusted code (every `RUN` in the user's Dockerfile); keep it away from nodes serving other users' apps;
  - **DRY** — one build instead of one per node. (Twelve-Factor: build → release → run.)
- **Registry:** `registry` (CNCF Distribution) in the host's root compose. All image traffic stays inside the laptop, and the demo does not depend on internet access. GHCR was rejected for user images: a round trip through the internet, a token on every node, and user code stored under a personal GitHub account.
- **Cost:** a third VM (RAM), `insecure-registries` on the nodes (no TLS — a known limitation), garbage collection for the registry and for node image caches.

## Builder: deploy as a job

| RPC | Kind | Purpose |
|---|---|---|
| `StartDeploy(deploy_id, spec)` | unary, fast | Starts a job in its own goroutine with **its own** context (not the request's), and returns immediately. |
| `WatchDeploy(deploy_id, offset)` | server streaming | Replays the job log from `offset`, then follows new lines (`tail -f`). Reconnectable. |
| `CancelDeploy(deploy_id)` | unary | Cancels the job's context; cancellation propagates into the Docker SDK and `git clone`. |
| `GetDeploy(deploy_id)` | unary | Job status, for reconciliation. |

**`WatchDeploy` stream messages** are one of two kinds (`oneof`): a log line **or** the final result (image tag + digest pushed to the registry).

**Stream completion:**
- success → the last message is the result, status `OK`;
- failure → a gRPC error status; log lines already received stay with the client.

### Job state on disk

- Each job's log is a file on the node's disk (e.g. `/var/lib/bultd/deploys/<id>.log`).
- Next to it, the **job status** is persisted: `running` / `succeeded` / `failed` + reason. Memory alone is not enough — the agent restarts too.
- On startup, the agent marks every job still in `running` as `failed: agent restarted`.
- TODO: retention policy for old logs and statuses.

## Runner: replicas

The runner only receives a reference to a ready image (`image@sha256:…`). RPCs are named by meaning (`Replica`), not by implementation (`Container`), so the contract does not depend on Docker vs containerd.

| RPC | Kind | Purpose |
|---|---|---|
| `RunReplica(replica_id, image@digest, port/limits/env…)` | unary, generous deadline | Pull (if not cached) + run. Idempotent on `replica_id`. Sets container log rotation (`max-size`/`max-file`). |
| `StopReplica(replica_id)` | unary | `docker stop`: the container stays, **its logs are kept** (needed to debug crashes). |
| `StartReplica(replica_id)` | unary | Starts a previously stopped replica. |
| `RemoveReplica(replica_id)` | unary | Deletes it for good, logs included. |
| `ListReplicas()` | unary | All replicas labeled `bult.managed` with their state — for reconciliation, including finding orphans. |
| `Logs(replica_id, tail, follow)` | server streaming | Without `follow`: last N lines, then end. With `follow`: live stream (`docker logs -f`). |

- **Redeploy is not an RPC — it is orchestration in the control plane:** `RunReplica` with the new digest → on success, remove the old ones. "New first, then old" = a rolling update without downtime.
- **Replica states:** `running` / `exited` (crashed or stopped, logs available) / removed. More states than "stop = remove" — the price of keeping logs.
- **Cleanup of stopped replicas** is decided by the **control plane**: after a new version starts successfully, it calls `RemoveReplica` for the old stopped ones. If the new start fails, old ones are kept as debugging evidence. If the control plane dies midway, reconciliation via `ListReplicas` finds the leftovers. (kubelet does the same: it keeps the last dead container for `kubectl logs --previous`.)

## Images: tag + digest

- A release record stores **both**: the tag for humans/UI, the **digest** (`@sha256:…`) for running on nodes.
- Tags are **never reused**: every build gets a new unique tag (deploy id / release number). A tag is a movable pointer; a reused tag would make a rollback run code that was never deployed as that release.
- Nodes keep the current and previous image of each app in their local cache for fast rollback without a pull. The cache is an optimization, not the source of truth: replicas always run by digest (`image@sha256:…` is taken from the cache if present, otherwise exactly that image is pulled). This guarantees identical replicas of a release on every node.

## IDs and idempotency

- The control plane creates the record in its DB first, then calls the agent with that ID.
- Reason — retries: a `StartDeploy`/`RunReplica` response can be lost and the control plane will retry. With a control-plane ID the retry is safe (**idempotency**; the ID is an idempotency key, like Stripe's `Idempotency-Key`). With an agent-generated ID, a retry would start a second build and leave an orphan job.
- A repeated call with a known ID:
  - same spec → `OK`, as if it were the first call; nothing new is started;
  - different spec → `ALREADY_EXISTS` (not a retry — a control-plane bug).

## Error codes

| Situation | Code | Why |
|---|---|---|
| Build failed because of the user's repo (broken Dockerfile, missing package) | `FAILED_PRECONDITION` | the request is valid, external state is broken; retrying is pointless until the repo is fixed |
| Docker daemon on the node is unavailable | `UNAVAILABLE` | transient environment problem; retry later or on another node |
| Something that "cannot happen" (panic, impossible Docker response) | `INTERNAL` | a bug; do not retry blindly |
| Unknown `deploy_id` / `replica_id` | `NOT_FOUND` | no such job/replica (or already cleaned up) |
| Known ID with a different spec | `ALREADY_EXISTS` | see [IDs and idempotency](#ids-and-idempotency) |

## Cancellation and lifecycle

- **User closes the tab** → only the SSE connection to the browser closes; the job keeps running. On return, `WatchDeploy(id, 0)` replays the whole log.
- **User presses Cancel** → the control plane calls `CancelDeploy` → the agent cancels the job's context.
- **Control plane restarts** → the job on the node continues; the new process finds `building` in the DB and reattaches via `WatchDeploy(id, offset)`.
- **Agent restarts (SIGTERM)** → stops accepting `StartDeploy`, gives running builds a short grace period, then cancels their contexts; unfinished jobs are marked `failed`. The grace period must fit within systemd's `TimeoutStopSec`.
- **Go:** cancellation arrives via `ctx.Done()`; the context must reach the Docker SDK and `exec.CommandContext`, otherwise work leaks.
- **Python:** asyncio task cancellation plays the role of a context (`task.cancel()` → `grpc.aio` closes the stream).

## Deadlines

Rule: **every call from the control plane has a deadline**, and it is longer than the operation itself. In `grpc.aio`, a call without `timeout=` can hang forever.

| RPC | Deadline (order of magnitude) | Why |
|---|---|---|
| `StartDeploy` | ~10 s | only creates the job; clone/build run inside it |
| `GetDeploy`, `CancelDeploy`, `ListReplicas`, `StartReplica`, `RemoveReplica` | ~5–10 s | fast operations |
| `StopReplica` | ~20 s | `docker stop` waits the grace period (10 s) before SIGKILL — the deadline must exceed it |
| `RunReplica` | ~3–5 min | includes pulling the image |
| `WatchDeploy`, `Logs(follow)` | none | long-lived by design |

**Long streams without a deadline are not unprotected.** A node that disappears silently leaves a half-open TCP connection, and the stream hangs forever → a zombie `building`. Protection:
1. **gRPC keepalive** (HTTP/2 pings) on the client channel and the server — a dead peer becomes `UNAVAILABLE`;
2. **consumer cancellation** — `Logs(follow)` lives only while the browser's SSE connection is open;
3. **reconnection** — the deploy watcher re-calls `WatchDeploy(id, offset)` after a drop.

A deadline answers "how long to wait for the result"; keepalive answers "is the peer still alive".

## Costs and limitations

- The agent is stateful: a job registry, files on disk, and their cleanup.
- If a node dies, its build logs are lost (that deploy has failed anyway). At scale, logs are additionally shipped to central storage (Loki / Elasticsearch / S3) — a point for the report's "how this would scale" section.
- No authentication between control plane and agents; nodes rely on network isolation (private Multipass network). A cloud node would require mTLS or a mesh such as Tailscale.

## Open questions

- Retention policy for build logs and job statuses on the builder.
