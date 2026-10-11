# ADR: Control plane structure

Status: accepted, 2026-10-11. Applies to `control-plane/app/`.

## Context

The control plane started as a layer-first layout (`api/`, `schemas/`, `services/`). Once CRUD, repositories and cross-domain operations appeared, every change touched four folders. The owner's existing convention (a Django backend: view → service → repository → model, facade-only access between domains, a central error-code registry, side effects after commit) is translated here to FastAPI, fixing the debts recorded there (domain errors coupled to the HTTP framework, untyped `dict` inputs, leaking query objects, oversized files).

Goal of the pattern: **easy to change**. A typical change should touch one domain folder (plus `core/` at most).

## Decision

### Layout — domain first, one folder per layer

```
app/
  core/           config.py (pydantic-settings), errors.py, error_codes.py,
                  exception_handlers.py, logging.py, deps.py (settings, agents, routes, event collector),
                  events.py (in-process event bus)
  apps/
    routers/      HTTP only
    schemas/      Pydantic input/output models
    services/     domain rules; facade.py = the domain's only public entry point
    repositories/ storage behind a Protocol (in-memory now, SQLAlchemy once PostgreSQL storage lands)
    events.py     events this domain publishes (frozen dataclasses)
    tests/
    deps.py       Depends wiring for this domain
  deploys/        same shape; services/runner.py is the deploy saga orchestrator;
                  handlers.py = subscribers of other domains' events: thin entry points like routers, call services only (wired in main.py only)
  agents/         infrastructure: gRPC clients to node agents
  ingress/        infrastructure: route versions shared with the nginx sidecar
  main.py
```

### Rules

1. **Layers:** router → service → repository. Routers never import repositories or models. Services never import FastAPI.
2. **Between domains only through the facade:** `from app.apps.services.facade import AppsFacade` (explicit methods; the service behind it is private) and, for FastAPI wiring, `from app.apps.public import AppsFacadeDep`. Never another domain's `deps`, repository or concrete service module. Enforced by `import-linter` contracts, which also keep FastAPI/Starlette out of services, repositories, `core.errors` and `core.events`.
3. **Cross-domain reactions go through events, not imports.** `deploys → apps` (facade); domains → `agents`, `ingress`, `core`; `apps` knows nothing about `deploys`. When something in one domain must trigger work in another (deleting an app cleans up deploys, replicas, routes), the owner publishes a frozen-dataclass event defined in its own `events.py` (`app.apps.events.AppDeleted`); the subscriber (`deploys/handlers.py`) imports the type from there. All subscriptions are wired in one place, `main.create_app` (bus on `app.state`, no global); `core.events` imports no domain. **Delivery is synchronous and after commit:** `publish` only queues in a per-request collector; the `get_event_collector` dependency (`scope="function"`, so its post-`yield` code runs before the response is sent — default scope runs it after) drains the queue after the unit of work and awaits every handler in order. A handler exception propagates to the exception handler (error response, never swallowed); an endpoint exception skips the drain, so the queue is dropped. Outside a request use `await bus.dispatch(event)`.
4. **Errors:** services raise `core.errors.AppError` subclasses carrying an `ErrorCode`, a safe `detail`, an optional `field` and an HTTP-like `status` (a plain int — no framework import). One exception handler renders `{detail, code, trace_id, field?, fields?}`; request validation errors become `code: "validation_error"` with `fields`; anything unknown becomes `500 internal_error` without exception text. Routers contain no `try/except`.
5. **Transactions (once PostgreSQL storage lands):** one transaction per request — the `get_session` dependency commits on success and rolls back on error; services `flush()`. Background tasks (the deploy saga) open their own session from the session factory. Side effects on other systems (agents, ingress) happen after the data they depend on is committed.
   **Ordering constraint:** commit must happen before events are drained. The session dependency must be function-scoped and commit before the event collector drains (e.g. drain inside the session dependency after commit, or make the collector depend on the session so teardown order is commit → drain); a request-scoped session would commit after the response.
6. **Typed inputs:** services take Pydantic input models or explicit arguments, never raw `dict`s. Repositories return domain objects, not query builders.
7. **Settings:** `pydantic-settings`, prefix `BULT_`; secrets as `SecretStr`. Derived values that depend on settings (e.g. an app's public URL) are computed by services, not by schemas.
8. **Tests next to the domain** (`app/<domain>/tests/`); shared fixtures and cross-domain tests in `control-plane/tests/`. In-memory repositories double as test fakes.

## Alternatives considered

| Option | Why not |
|---|---|
| Layer-first (`api/`, `services/`, `schemas/`) | a feature change spans many folders; no natural boundary between domains |
| Transaction per service method (`@atomic`-like) | nested `begin()` when a service calls another through a facade needs extra machinery; per-request is simpler at this scale |
| Domain errors without status, mapped in each router | `try/except` in every handler; the mapping is duplicated |
| Exceptions inheriting `HTTPException` | the domain would depend on FastAPI (the owner's recorded Django debt) |
| Cross-domain orchestrator (`lifecycle.py` calling both facades) | every new reaction edits the orchestrator, which imports every domain and becomes the place that knows everything; the publisher stays unaware with events |
| Event bus, fire-and-forget (`create_task`) | the client gets 204 while cleanup may still fail unseen; tests need sleeps |
| Event bus, delivered before commit | a handler may act on data that is later rolled back |
| **Event bus, queued and drained synchronously after commit (chosen)** | control flow is hidden but small: one subscription list in `main.py`, one drain point; failures are visible in the response and tests are deterministic |
| Facade only for heavy domains | chosen against by the owner: a facade per domain from the start keeps the rule uniform |

## Consequences

- More files and packages than the code strictly needs today; the uniform shape is the point.
- Replacing storage touches only `repositories/` and wiring in `deps.py`.
- The web client's error normalizer follows the new error format.
- Delivery is in-process and not durable: if the process dies between commit and drain, or a handler fails after the commit, the reaction is lost (the request reports the failure; the app row is already gone).

**Next step: transactional outbox for reliable delivery across crashes.** The event is written to an `outbox` table in the same transaction as the data and a relay delivers it at-least-once (idempotent handlers), so a crash between commit and handler no longer loses the cleanup. Planned together with PostgreSQL storage.
