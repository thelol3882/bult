# express-hello

Demo application for the bult **Express preset**. It has no Dockerfile on
purpose: the platform supplies one.

- `GET /` — app name, hostname (container ID — shows which replica answered), `$PORT`, uptime
- `GET /healthz` — liveness probe

Run locally: `npm ci && PORT=3000 npm start`
