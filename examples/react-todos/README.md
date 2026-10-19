# react-todos

Frontend of the bult **path routing** demo: a Vite + React page for the **static preset**.
Pairs with [`fastapi-todos`](../fastapi-todos). No Dockerfile on purpose: the platform supplies one.

It calls the API with relative paths only (`/api/todos`) and shows which backend replica
answered (the `X-Replica` response header). It knows nothing about the backend's address:
on bult the `/api` path of this app's domain is routed to the backend app.

Build: `npm ci && npm run build` (output in `dist/`).
Run locally: start `fastapi-todos` on port 8000, then `npm ci && npm run dev` (Vite proxies `/api`).

## Deploy on bult

1. App `todos-api`: preset `fastapi`, subdir `examples/fastapi-todos`.
2. App `todos`: preset `static`, subdir `examples/react-todos`.
3. Deploy both, then add the route `/api` -> `todos-api` to `todos`
   (app page, "Routes"; API: `PUT /apps/todos/routes`).
4. Open `todos.bult.localhost`. Scale `todos-api` to 2+ replicas and watch the replica name change
   (each replica keeps its own in-memory list).
