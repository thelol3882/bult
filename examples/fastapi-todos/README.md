# fastapi-todos

Backend of the bult **path routing** demo: a todo API for the **FastAPI preset**.
Pairs with [`react-todos`](../react-todos). No Dockerfile on purpose: the platform supplies one.

- `GET /api/todos`, `POST /api/todos` (`{"title": "..."}`), `DELETE /api/todos/{id}`
- `GET /api/healthz` — liveness probe
- every response carries `X-Replica` (container hostname): which replica answered
- `GET /docs` — Swagger UI

The list lives in memory of each replica, so with `replicas > 1` each replica has its own todos
(refresh the UI and the list changes depending on who answers). That is the point of the demo.

Run locally: `pip install -r requirements.txt && PORT=8000 uvicorn main:app --port 8000`

## Deploy with react-todos on bult

1. Create app `todos-api`: preset `fastapi`, subdir `examples/fastapi-todos`.
2. Create app `todos`: preset `static`, subdir `examples/react-todos`.
3. Deploy both. Then on the `todos` app page add the route `/api` -> `todos-api`
   (API: `PUT /apps/todos/routes` with `[{"path": "/api", "app": "todos-api"}]`).
4. Open `todos.bult.localhost`: the page is served by `todos`, `/api/...` by `todos-api`
   (the path is passed on unchanged), same origin, no CORS.
