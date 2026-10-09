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
- Same `bultd` binary everywhere; the role comes from config: `builder`, `runner`, or both (handy for a single dev VM).
- **Two gRPC services in package `bult.agent.v1`:** `BuildService` (builder RPCs) and `RuntimeService` (runner RPCs). At startup `bultd` registers only the services of its configured roles, so a misrouted call (e.g. `RunReplica` on a builder) fails with `UNIMPLEMENTED` from gRPC itself — no per-handler role checks to forget.
- Why not build on worker nodes:
  - **noisy neighbor** — a build (Next.js/TypeScript: gigabytes of RAM) starves co-located apps, up to OOM kills;
  - **reproducibility** — two builds of the same commit can produce different images (unpinned dependencies), so replicas of "the same release" would run different code;
  - **rollback** — the image lives centrally; rolling back means running the previous image on any node, no rebuild;
  - **security** — a build executes untrusted code (every `RUN` in the user's Dockerfile); keep it away from nodes serving other users' apps;
  - **DRY** — one build instead of one per node. (Twelve-Factor: build → release → run.)
- **Registry:** `registry` (CNCF Distribution) in the host's root compose. All image traffic stays inside the laptop, and the demo does not depend on internet access. GHCR was rejected for user images: a round trip through the internet, a token on every node, and user code stored under a personal GitHub account.
- **Cost:** a third VM (RAM), `insecure-registries` on the nodes (no TLS — a known limitation), garbage collection for the registry and for node image caches.

## Builder (`BuildService`): deploy as a job

| RPC | Kind | Purpose |
|---|---|---|
| `StartDeploy(deploy_id, spec)` | unary, fast | Starts a job in its own goroutine with **its own** context (not the request's), and returns immediately. |
| `WatchDeploy(deploy_id, offset)` | server streaming | Replays the job log from `offset`, then follows new output (`tail -f`). Reconnectable. |
| `CancelDeploy(deploy_id)` | unary | Cancels the job's context; cancellation propagates into the Docker SDK and `git clone`. |
| `GetDeploy(deploy_id)` | unary | Job status, for reconciliation. |

**Contract (decided 2026-10-07).** `StartDeployRequest`: `deploy_id`, `app_id`, `Source { repo_url, branch }`. `StartDeploy`, `GetDeploy` and `CancelDeploy` all answer with the job as the agent sees it: `deploy_id`, `state` (`UNSPECIFIED = 0`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`), `commit_sha`, `image` (`ImageRef`, only on success — the exact input of `RunReplica`), `error` (user-facing text), `started_at`, `finished_at`.

- **Own context + job registry.** The handler's context dies when `StartDeploy` returns, so a job runs under its own cancellable context; the agent keeps `deploy_id → job` (with its `cancel`) under a mutex. The same registry makes `StartDeploy` idempotent and lets `CancelDeploy` reach the job.
- **Atomic status writes:** temp file in the same directory → `fsync` → `close` → `rename`. `rename` within one filesystem is atomic, so `status.json` is always either the old or the new content; a temp file elsewhere (e.g. tmpfs `/tmp`) would turn `rename` into a non-atomic copy. The build log is append-only.
- **Image naming:** `<registry>/<app_id>:<deploy_id>` — repository per app, tag per build, never reused. The digest exists only after push and is read back from the registry. Provenance labels: `org.opencontainers.image.revision` (commit SHA), `org.opencontainers.image.source` (repo URL), `bult.deploy_id`.
- **Registry address lives only in the builder's config** (`--registry`). The build result carries a complete `ImageRef`; the control plane stores and forwards it to `RunReplica` without knowing the registry.
- **`ImageBuild` output** is a JSON message stream like pull, but the SDK offers no `Wait` helper: the agent decodes it, appends text to `build.log`, and treats an error message as a failed build.

- **Dockerfile presets live in the control plane, not the agent (decided 2026-10-08).** The agent is mechanism ("build this context with this Dockerfile"); supported frameworks are product policy and change often — a new preset must not require rebuilding and rolling out agents. The control plane also stores the exact Dockerfile text with each release, so releases stay reproducible after a template changes. MVP: templates as files in the control-plane repository; admin CRUD is level 3.
- **`StartDeployRequest.dockerfile`** (text): set → build with it, even if the repository has its own; empty → the repository's `Dockerfile`. The agent has no precedence rules of its own. The provided file is written as `.bult/Dockerfile` and passed as the build's Dockerfile path, so the user's file is never overwritten. No Dockerfile anywhere is discovered inside the job → `FAILED` with a user-facing message, not an RPC error.
- **`Source.subdir`** (decided 2026-10-09): the app's root inside the repository (monorepos, like Heroku/Render "root directory"); build context, `.dockerignore` and the Dockerfile are relative to it. The string must be relative, canonical and free of `..`; after clone the real path is resolved with symlinks and must stay inside the checkout — a valid name can still be a symlink to `/etc`.
- **Ports convention:** the host port is allocated by the runner; the container port is owned by the control plane via the `PORT` convention — templates listen on `${PORT}`, and `RunReplica` passes the same number as `env PORT` and `container_port`.

**`WatchDeploy` stream messages** are one of two kinds (`oneof`): a log chunk **or** the final result (image tag + digest pushed to the registry).

**Resuming by byte offset.** Every log chunk carries `offset` — the byte position in the agent's log file where the chunk starts; only the agent knows it exactly. A receiver resumes from `offset + len(data)`. Chunk counts are not usable (reads return however many bytes are available, not fixed-size blocks). Unknown position → `0`; build logs are small, replaying is cheap.

- **Browser:** each SSE event's `id` is the **end** of the chunk (`offset + len(data)`). `EventSource` resends it automatically as `Last-Event-ID` on reconnect → control plane → `WatchDeploy(id, offset)`. No offset is stored server-side. (Using the chunk start would replay the last chunk twice.)
- **Control-plane watcher:** does not need logs, only the result; after a restart it reattaches anywhere or calls `GetDeploy`.

**Log data is `bytes`, not `string`.** Protobuf `string` must be valid UTF-8 and Go's marshaller rejects anything else, which would kill the stream. Build output is not guaranteed UTF-8: legacy encodings, binary noise, and — most commonly — a multi-byte character split across two fixed-size read chunks. Bytes travel untouched; the control plane decodes at the edge (`decode("utf-8", errors="replace")`) before sending text to the browser.

**Stream completion (revised 2026-10-08).** The stream **always ends with a `Deploy` message** in a terminal state (`SUCCEEDED` / `FAILED` / `CANCELLED`, with `error`) and status `OK`. A status code describes the RPC itself, not the build it observes — like `GET /builds/42` answering `200` with `{"status":"failed"}`. An error status means the watch itself failed: `NOT_FOUND` (no such deploy), `INVALID_ARGUMENT` (bad id, negative offset), `INTERNAL` (log unreadable), `CANCELLED` (client left). The control plane handles every build ending through one path. *(Lesson 02 said "failure → a gRPC error status"; replaced.)*

**Following the log** is polling: read to EOF, wait ~200 ms, read again. Build logs tolerate the latency, the cost is one `read` per watcher per tick, and one code path serves running, finished and pre-restart builds alike — the file is the single source. An in-memory fan-out would not survive a restart, would still need the file for offset replay, and would let a slow watcher stall the build. `inotify` is a later optimisation (even `tail -f` keeps polling as a fallback).

**End-of-stream race:** the handler takes a **status snapshot first, then reads to EOF**, and sends the final `Deploy` only if the snapshot was terminal. This is correct because the writer does the opposite — the whole log, then the status — so a terminal snapshot guarantees the file is complete.

### Job state on disk

- Each job's log is a file on the node's disk (e.g. `/var/lib/bultd/deploys/<id>.log`).
- Next to it, the **job status** is persisted: `running` / `succeeded` / `failed` + reason. Memory alone is not enough — the agent restarts too.
- On startup, **before serving**, the agent marks every job still in `running` as `failed: agent restarted` (covers `kill -9` and power loss).
- **Cancellation cause:** jobs run under `context.WithCancelCause`; the manager owns the base context. `CancelDeploy` cancels a job with "cancelled by user" → `CANCELLED`; agent shutdown cancels the base context with "agent shutdown", inherited by every job → `FAILED: agent restarted`. `ctx.Err()` is identical for both; `context.Cause` tells them apart. Shutdown waits (bounded) for jobs to persist their final status.
- TODO: retention policy for old logs and statuses.

## Runner (`RuntimeService`): replicas

The runner only receives a reference to a ready image (`image@sha256:…`). RPCs are named by meaning (`Replica`), not by implementation (`Container`), so the contract does not depend on Docker vs containerd.

| RPC | Kind | Purpose |
|---|---|---|
| `RunReplica(replica_id, image@digest, port/limits/env…)` | unary, generous deadline | Pull (if not cached) + run. Idempotent on `replica_id`. Sets container log rotation (`max-size`/`max-file`). |
| `StopReplica(replica_id)` | unary | `docker stop`: the container stays, **its logs are kept** (needed to debug crashes). |
| `StartReplica(replica_id)` | unary | Starts a previously stopped replica. |
| `RemoveReplica(replica_id)` | unary | Deletes it for good, logs included. |
| `ListReplicas()` | unary | All replicas labeled `bult.managed` with their state — for reconciliation, including finding orphans. |
| `Logs(replica_id, tail, follow)` | server streaming | Without `follow`: last N lines, then end. With `follow`: live stream (`docker logs -f`). |

- **Env vars are `repeated EnvVar{name, value}`, not `map<string,string>`:** each variable can grow its own attributes later (a `secret` flag to mask it in UI/logs, a reference to a secret store instead of a literal value) without a breaking change, and order is preserved.
- **Redeploy is not an RPC — it is orchestration in the control plane:** `RunReplica` with the new digest → on success, remove the old ones. "New first, then old" = a rolling update without downtime.
- **Replica states:** `running` / `exited` (crashed or stopped, logs available) / removed. More states than "stop = remove" — the price of keeping logs.
- **Cleanup of stopped replicas** is decided by the **control plane**: after a new version starts successfully, it calls `RemoveReplica` for the old stopped ones. If the new start fails, old ones are kept as debugging evidence. If the control plane dies midway, reconciliation via `ListReplicas` finds the leftovers. (kubelet does the same: it keeps the last dead container for `kubectl logs --previous`.)

## Runner on Docker

- **Client:** Docker Engine API over `/var/run/docker.sock` via the Go SDK (`github.com/moby/moby/client`), not the `docker` CLI: typed results and errors, `context` propagation, streams.
- **App identity is explicit:** `RunReplicaRequest.app_id` (opaque string). Not derived from `image.repository` — that would be string parsing by convention, coupling to the builder's naming, and one image can serve two apps. An id, not a name: apps can be renamed.
- **Labels hold immutable facts only we know:** `bult.managed=true`, `bult.replica_id`, `bult.app_id`, `bult.image.repository`, `bult.image.digest`. Labels cannot change after creation, so mutable state (running/exited, ports, timestamps) is always read from Docker — no second copy of the truth. `ListReplicas` is one label-filtered query.
- **Container name `bult-<replica_id>` is the idempotency lock:** a retried `RunReplica` hits `409 Conflict` from dockerd atomically, no agent-side mutex. What the agent returns on a conflict is decided with error mapping.
- **One user-defined network per app** (`bult-app-<app_id>`): Docker blocks traffic between networks and adds DNS by container name; per app, not per replica, so a future add-on database can join it. Limitation: published host ports are still reachable from any container via the gateway.
- **Image pull is a stream:** the HTTP status is sent before the work, so a mid-pull failure arrives as an `error` message inside the body. Success = stream read to the end **and** no error message; closing early cancels the pull on the daemon side.
- **Limits:** CPU is compressible (over limit → throttled, `NanoCPUs = millicores × 10⁶`), memory is not (over limit → OOM kill, exit code 137, `OOMKilled=true`).

- **Host ports are allocated by the agent, not by Docker.** An empty `HostPort` lets Docker pick a new port on every start, so a stop/start could move the replica — and if the old port goes to another replica, nginx silently serves the wrong user's app (fail open). An explicit port is stored in the container config and survives stop/start. A stopped replica keeps its port until `RemoveReplica`; the port is released only after the container is gone.
- **Source of truth for taken ports is Docker:** `HostConfig.PortBindings` (desired config, kept while stopped) of all `bult.managed` containers, not `NetworkSettings.Ports` (runtime, empty when stopped). The agent rebuilds an in-memory set from it at startup, before serving; afterwards the set is a cache updated on reserve/release. A leaked port heals on agent restart.
- **Concurrency:** gRPC handlers run in parallel goroutines, so "find a free port + mark it" is one critical section under a mutex (check-then-use across goroutines is a TOCTOU race: two replicas get the same port, the second fails only at start). Docker calls never run under the lock — a long pull must not block other RPCs. A reserved port is released on every error path.
- **Idempotency = desired end state.** Repeated `StopReplica`/`StartReplica` on an already stopped/running replica → `OK` (dockerd answers 304, the SDK returns nil). `RemoveReplica` of a missing replica → `OK` (the agent cannot tell "never existed" from "removed, response lost", and the caller does not care). `StopReplica`/`StartReplica` of a missing replica → `NOT_FOUND`. A repeated `RunReplica` is matched by the identity labels (`app_id`, `image.repository`, `image.digest`, `container_port`): same → `OK` with the existing replica; different → `ALREADY_EXISTS`. Limits and env are not compared in the MVP (a mismatch there is a control-plane bug; a `bult.spec_hash` label would cover the full spec).

## Build input: source and context

- **Source = HTTPS URL + branch, both untrusted.** Allow-list: scheme `https` only, a host, no userinfo (credentials would land in the user-visible build log); branch must be a valid git ref name and must not start with `-`. Private repositories and SSH are out of scope for the MVP.
- **`git` is executed, not embedded.** Unlike Docker, clone needs no output parsing (success = exit code), has few error kinds (all go to the build log), supports cancellation via `exec.CommandContext`, and `git` ships with Ubuntu; `go-git` would be a heavy, slower dependency. `go get` and BuildKit exec git too.
- **Hardening of the git call:** no shell (`exec` passes argv directly, so `;` is inert); `--` before positional arguments against option injection (`--upload-pack=…`); `GIT_ALLOW_PROTOCOL=https` as a second line of defence; `GIT_TERMINAL_PROMPT=0` so a private repo fails instead of waiting for a password; no submodules.
- **`--depth 1`, record the commit SHA.** A branch is a movable pointer; the SHA (`git rev-parse HEAD`) is stored with the build so a release maps to exact code. Rollback reuses the image by digest and never rebuilds.
- **Build context is a tar stream** built by `github.com/moby/go-archive` — the package the Docker CLI uses, so `.dockerignore` and symlink semantics match `docker build`. `.dockerignore` is applied client-side (dockerd does not), `.git` is always excluded, symlinks are archived as links and never followed (`secret -> /etc/shadow` would otherwise leak a build-node file). The stream is an `io.Pipe` fed by a goroutine: no temp tar on disk, but the returned `ReadCloser` must always be closed or the goroutine leaks.
- **Limitation — SSRF:** the build node can reach the internal network (registry, unauthenticated agents on `:50051`). URL validation cannot close this (a public name may resolve to a private address); the real fix is an egress firewall on the build node.

## Images: tag + digest

- A release record stores **both**: the tag for humans/UI, the **digest** (`@sha256:…`) for running on nodes.
- Tags are **never reused**: every build gets a new unique tag (deploy id / release number). A tag is a movable pointer; a reused tag would make a rollback run code that was never deployed as that release.
- Nodes keep the current and previous image of each app in their local cache for fast rollback without a pull. The cache is an optimization, not the source of truth: replicas always run by digest (`image@sha256:…` is taken from the cache if present, otherwise exactly that image is pulled). This guarantees identical replicas of a release on every node.

## Message conventions

- **Every RPC has its own `XxxRequest` / `XxxResponse`**, even when empty — never `google.protobuf.Empty`, never shared between RPCs. Adding a field to an RPC's own request is backward compatible; changing an RPC's request type is not, and a shared message would leak fields into unrelated RPCs. Common types (e.g. resource limits) are nested inside the per-RPC envelopes.

- **Image reference is structured:** `ImageRef { repository, digest }`, where `repository` includes the registry host (`192.168.252.1:5050/myapp-42`) and `digest` is a separate required field (`sha256:…`). The "run by digest only" rule is visible in the contract and enforced by the agent (empty digest → `INVALID_ARGUMENT`); no parsing of reference strings. The agent joins them into `repository@digest` for the Docker SDK. No tag: the runner never uses it (the control plane keeps tags for humans).
- **Opaque IDs are `string`** (`replica_id`, `deploy_id`): the agent stores and echoes them, never does arithmetic on them, and must not depend on how the control plane generates them (int, UUID, …).
- **Ports:** protobuf has no 16-bit integers; `uint32` costs nothing extra (varint encoding — `8080` takes 2 bytes). The agent validates 1–65535 → otherwise `INVALID_ARGUMENT`. The request carries the **container** port the app listens on; the agent allocates the **host** port and returns it in the response (what nginx upstream needs).
- **Resource limits** live in a shared `Resources` message nested in `RunReplicaRequest`. `0` is meaningless for a limit, so it is treated as "not set" and rejected (`INVALID_ARGUMENT`) — every replica runs with limits.
- **Units live in field names, integers only:** `cpu_millicores` (`int64`, 500 = half a core), `memory_bytes` (`int64`). No `float`: the scheduler sums limits against node capacity, and float rounding errors accumulate. No `int32` for bytes: it caps at ~2 GB. Both map directly to the Docker SDK (`NanoCPUs = millicores × 10⁶`, `Memory` in bytes).
- **Time is `google.protobuf.Timestamp`** (→ `time.Time` in Go, `datetime` in Python), never a unix `int64` or a string.

## Contract rollout

- `RuntimeService` is written first; `BuildService` is added to `v1` later, once `DeploySpec` is actually known (YAGNI). Adding a service to a package is backward compatible.
- Until the control plane consumes the contract, it may change freely; after that, only compatible changes (enforced by `buf breaking`).
  - 2026-10-05: `app_id` added as field 2 of `RunReplicaRequest` and `Replica`, renumbering the fields after it — a deliberate pre-consumer change. Once the control plane is a client (lesson 15), field numbers are frozen: new fields take the next free number, and logical grouping is expressed by their position in the file, not by the number.

## IDs and idempotency

- The control plane creates the record in its DB first, then calls the agent with that ID.
- Reason — retries: a `StartDeploy`/`RunReplica` response can be lost and the control plane will retry. With a control-plane ID the retry is safe (**idempotency**; the ID is an idempotency key, like Stripe's `Idempotency-Key`). With an agent-generated ID, a retry would start a second build and leave an orphan job.
- A repeated call with a known ID:
  - same spec → `OK`, as if it were the first call; nothing new is started;
  - different spec → `ALREADY_EXISTS` (not a retry — a control-plane bug).

## Error codes

A code is for the caller's **decision**, the message is for a human. The control plane has four reactions: retry here later, go to another node, do not retry (caller bug), do not retry (world is broken — the user or a build must fix it).

| Situation | Code | Caller's reaction |
|---|---|---|
| Docker daemon on the node is unavailable | `UNAVAILABLE` | retry later or on another node |
| Lost a race with an identical concurrent `RunReplica` (dockerd reserved the name before the replica is inspectable) | `ABORTED` | retry → finds the replica → `OK` |
| Host port range exhausted | `RESOURCE_EXHAUSTED` | schedule on another node |
| Invalid request (empty id, zero limit, port out of range) | `INVALID_ARGUMENT` | do not retry — control-plane bug |
| Known `replica_id` with a different spec | `ALREADY_EXISTS` | do not retry — control-plane bug (see [IDs and idempotency](#ids-and-idempotency)) |
| Image digest not in the registry; build failed because of the user's repo | `FAILED_PRECONDITION` | do not retry — the request is valid, the world is not; fail the release |
| Unknown `deploy_id` / `replica_id` | `NOT_FOUND` | the resource of the RPC itself is missing; except `RemoveReplica`, which answers `OK` (idempotent delete) |
| Client deadline expired / call cancelled | `DEADLINE_EXCEEDED` / `CANCELLED` | **outcome unknown** → idempotent retry with a deadline longer than the operation |
| Something that "cannot happen" | `INTERNAL` | a bug in the agent; do not retry blindly |
| Not implemented yet (`Logs` with `follow`) | `UNIMPLEMENTED` | — |

- `NOT_FOUND` is reserved for the RPC's own resource. A missing image is a precondition (`FAILED_PRECONDITION`), so the control plane can tell "no replica" from "no image".
- Context errors are mapped to `DEADLINE_EXCEEDED`/`CANCELLED` by the agent too (`status.FromContextError`), so cancellations do not pollute `INTERNAL` in logs and metrics.
- `ABORTED` was chosen over a per-`replica_id` lock: the race is rare (a retry while the first call is still in `create`), and the control plane must retry `UNAVAILABLE`/`DEADLINE_EXCEEDED` anyway. `singleflight` would be the upgrade path.
- Mapping lives in one place in the gRPC layer; the Docker layer returns domain sentinel errors and knows nothing about gRPC codes.

## Logs

- `Logs` without `follow` returns the last `tail_lines` lines (`0` → 100, max 10000) as several `LogsResponse` chunks (≤ 32 KB each, well under gRPC's 4 MB default message limit).
- Docker multiplexes stdout and stderr of a non-TTY container into one stream of frames (`[stream byte][3 zero bytes][uint32 BE length]` + payload). The agent demultiplexes it and merges **both streams into one in the original order** — like `kubectl logs` — because separate buffers would lose the interleaving, and the contract carries plain `bytes`. Separating streams later is a compatible contract change.
- `follow` is not implemented yet (`UNIMPLEMENTED`); it arrives with SSE streaming.

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
