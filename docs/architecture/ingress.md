# Ingress: routing apps to replicas

One nginx on the host routes `<app>.bult.localhost` to the replicas running on the nodes. The control plane decides *what* the routes are; a small sidecar next to nginx applies them. The control plane never touches nginx directly.

## Why a sidecar (decided 2026-10-11)

| Option | Verdict |
|---|---|
| Docker socket in the API container (`exec nginx -t`, `kill -s HUP`) | rejected: the socket is root on the host, so any API bug becomes root |
| Agent with an RPC next to nginx (push, e.g. `ApplyRoutes`) | production-like, but a new proto service, role and deployment; too costly for the course timeline |
| **Sidecar watching a shared volume (pull)** | chosen: no Docker access, survives its own restarts, simple protocol |

This is the same model as ingress-nginx in Kubernetes or consul-template: the agent next to the proxy reconciles it towards the desired state, instead of executing individual commands that could be missed.

## Protocol (shared volume `/routes`)

```
/routes/
  desired/<gen>/<app>.conf   API: the FULL set of app routes, version <gen>
  desired/LATEST             API: number of the latest version
  current -> desired/<gen>   sidecar: the applied version (nginx: include /routes/current/*.conf)
  status.json                sidecar: {"generation", "ok", "error", "applied_at"}
```

- **Full desired state, not deltas.** Every change renders all routes; deleting an app means its file is absent from the next version.
- **Atomic writes.** The API writes `desired/.tmp-<gen>/` and renames it to `desired/<gen>/`, then replaces `LATEST` (temp + rename). The sidecar replaces `status.json` the same way. Everything is on one volume, i.e. one filesystem.
- **Validate before it becomes live.** The sidecar swaps the `current` symlink (atomic rename), runs `nginx -c … -t`, and either reloads or swaps back and records the error. A broken config never stays live and never breaks the next nginx start.
- **Generations compared for equality.** The API waits until `status.json.generation` equals the version it wrote; on startup it continues numbering from disk.
- **Polling (1 s), not inotify.** File events are unreliable across Docker Desktop mounts on macOS.

## Stopped apps

An app with `replicas = 0` still has a name, so its subdomain must not look like "no such app". The generator emits a server block for it that includes `deploy/nginx/snippets/stopped.conf`: `503` and the static page `deploy/nginx/pages/stopped.html`, without `Retry-After` (nothing will bring the app back by itself) and with `Cache-Control: no-store`. The page is served by an `internal` location through `error_page 503`, so the status stays 503 and the page is not reachable as `/stopped.html`. A subdomain nobody owns still gets the default server's `404`.

```
server {
    listen 80;
    server_name <name>.<domain>;

    include /etc/nginx/bult/snippets/stopped.conf;
}
```

The snippet and the page live in the mounted `deploy/nginx` directory, next to the other platform config, so the sidecar's `nginx -t` checks them with the rest. A running route wins: an app is rendered as stopped only when it has no running deploy.

## Balancing and retries

Per app the generator writes:

```
upstream app_<name> {
    zone app_<name> 64k;
    [least_conn;]            # BULT_LB_ALGORITHM
    server <ip>:<port> max_fails=3 fail_timeout=10s;   # one per replica
    keepalive 16;
}
```

- **`zone`** puts the upstream state in shared memory: without it every nginx worker keeps its own round-robin counter and its own failure marks, so a few requests all land on one replica and one worker can keep sending to a replica another has already marked dead.
- **`max_fails` / `fail_timeout`** are passive health checks: 3 failed attempts within 10 s take the replica out of rotation for 10 s.
- **`keepalive 16`** reuses connections to the replicas. It needs HTTP/1.1 and an empty `Connection` header towards the upstream; both come from `nginx.conf` (`proxy_http_version 1.1`, `Connection` from the `$connection_upgrade` map, which is empty unless the client asked for an upgrade). The proxied locations deliberately set **no** `proxy_set_header`: one directive at that level would hide all of `nginx.conf`'s (`Host`, `X-Forwarded-*`).
- **Retries:** `proxy_next_upstream error timeout` with at most 2 tries. A refused connection means the request never reached a replica, so trying another one is safe even for `POST`; once a request was sent, nginx repeats only idempotent methods (never `POST`, and `non_idempotent` is not set). "Idempotent by the HTTP spec" does not mean the application's handler is.
- **Algorithm** is a platform setting, not a per-app one: `BULT_LB_ALGORITHM` = `least_conn` (default) | `round_robin` (no directive) | `ip_hash` (sticky by client address). The control plane validates it at start. `least_conn` is the default because of the benchmark in `bench/`: same p50, about a third shorter p95/p99 with mixed request durations, and +38% throughput when one replica is slow (round-robin keeps sending it a third of the traffic).

## Path routes

The owner of an app can hand paths of its domain to other apps, e.g. `todos.bult.localhost/api/…` to the app `todos-api`, while everything else stays with `todos` (a static frontend):

```
PUT /apps/todos/routes   [{"path": "/api", "app": "todos-api"}]
```

```
location /api/ {                 # prefix with the slash: /apiary is not caught
    proxy_pass http://app_todos-api;   # no URI part: the prefix is NOT stripped
    …
}
location / { proxy_pass http://app_todos; … }
```

- The target sees the same path the client sent (`/api/todos`), so the API's own docs, redirects and links work without a `root_path`, and the same URL works through the frontend's domain and through the backend's own subdomain. A bare `/api` gets nginx's 301 to `/api/`.
- Why not a separate backend domain: the page and the API share one origin, so there is **no CORS**, no preflight, and cookies stay first-party.
- Rules: up to 5 paths, `^/[a-z0-9][a-z0-9_-]*(/…)*$` (a trailing slash is normalized away), `/` is not allowed, paths are unique, the target is another app with the **same owner** (otherwise anybody could put someone else's backend under their domain, or take over a path). `PUT` replaces the whole list and re-applies the ingress at once; deleting an app removes the routes that point to it.
- A route whose target has no running replica (stopped, or its nodes are unhealthy) answers `503` with `{"detail": "backend is not running", "code": "backend_unavailable"}` (JSON, `no-store`), not the frontend's `index.html`. The frontend itself is still served.
- Routes live in `apps.routes` (JSONB). The route generator reads them through the apps facade; the apps domain announces a change with the `AppRoutesChanged` event and the deploys domain re-applies the ingress.

## Lifecycle

- A deploy becomes `running` only after its route is applied (`status.json` confirms the generation), so `running` means "the URL works".
- Deleting an app re-applies routes without it; stopping one re-applies them with the stopped block.
- An app has one `upstream` block with a `server node_ip:host_port …;` line per running replica on a **ready** node (see "Balancing"). When a node becomes unhealthy the control plane re-applies the routes without its replicas; when it returns they are added back (`nodes.md`). An app whose replicas are all on unhealthy nodes has no server block and the default server answers `404`.
- A short `proxy_connect_timeout` keeps a dead node from stalling requests for 60 s, which matters between a node dying and the ~15 s it takes to be called unhealthy.

## Limitations

- Balancing has no weights and no active health checks of the replicas (only the passive `max_fails`); `ip_hash` is the only stickiness.
- Path routes are one level deep: a target's own path routes are not followed, and a target must run for its own route to work.
- One ingress instance; no TLS (`*.bult.localhost` is plain HTTP in the dev setup).
- Up to ~1 s of propagation delay (polling).
- The sidecar runs in the background of the ingress container without supervision: if it dies, nginx keeps serving the last applied routes but new versions are never applied, and the API times out waiting for `status.json`. A supervisor (s6, supervisord) or a separate container with a health check would fix it.
- When publishing a route fails, the deploy is marked failed and its replica is removed as a compensation (best effort, see `deploy-saga.md`).
