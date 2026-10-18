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

## Lifecycle

- A deploy becomes `running` only after its route is applied (`status.json` confirms the generation), so `running` means "the URL works".
- Deleting an app re-applies routes without it; stopping one re-applies them with the stopped block.
- An app has one `upstream` block with a `server node_ip:host_port;` line per running replica on a **ready** node (nginx's default round-robin). When a node becomes unhealthy the control plane re-applies the routes without its replicas; when it returns they are added back (`nodes.md`). An app whose replicas are all on unhealthy nodes has no server block and the default server answers `404`.
- A short `proxy_connect_timeout` keeps a dead node from stalling requests for 60 s, which matters between a node dying and the ~15 s it takes to be called unhealthy.

## Limitations

- Balancing is plain round-robin, with no weights, no health checks of the replica itself and no sticky sessions; `max_fails`/`fail_timeout` (passive checks) are not set yet.
- One ingress instance; no TLS (`*.bult.localhost` is plain HTTP in the dev setup).
- Up to ~1 s of propagation delay (polling).
- The sidecar runs in the background of the ingress container without supervision: if it dies, nginx keeps serving the last applied routes but new versions are never applied, and the API times out waiting for `status.json`. A supervisor (s6, supervisord) or a separate container with a health check would fix it.
- When publishing a route fails, the deploy is marked failed and its replica is removed as a compensation (best effort, see `deploy-saga.md`).
