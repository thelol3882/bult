# bult web

Dashboard and landing page for bult (Next.js). Talks to the control plane REST API; each app is served at `https://<name>.bult.localhost`.

Stack: Next 16 (App Router, React Compiler, standalone output), React 19, TypeScript, Mantine 8, Redux Toolkit + RTK Query, nuqs, Vitest. Desktop only (>= 1280 px).

## Layers

```
src/app        thin routes (page.tsx -> widget)
src/widgets    compositions; data via feature hooks
src/features   <feature>/{api,hooks,components,pages,services,types} + index.ts (features never import each other)
src/shared     api (baseApi, error normalizer), components, utils, types
src/store      makeStore + StoreProvider        src/theme   tokens.css + Mantine theme
```

Import direction: `app -> widgets -> features -> shared`. `store` and `theme` sit above `shared`: the store wires `shared`'s `baseApi` (and `app/providers` wires both). `shared` may import `theme` (status colors) but never `features`, `widgets` or `store`.

## Routes

```
/                landing
/apps            apps list (dashboard)
/new             create an app (dashboard; highlights "Apps")
/apps/[name]     app detail + deploy
```

`/new` lives outside `/apps/*` on purpose: an app may be named `new`.

## Error pages

`src/features/error` (themed full-screen sky, status code with the middle "0" as a floating cloud):

- `NotFoundPage` (404): `app/not-found.tsx`, and inline in the app detail when the API answers 404 for the app.
- `BackendUnavailablePage` (503): shown when the API is unreachable (`normalizeError` -> status `network`), "Try again" refetches the query.
- `app/global-error.tsx`: last-resort 500 screen that works without the root layout or Mantine.

## Commands

```
pnpm install
pnpm dev          # http://localhost:3000
pnpm lint | pnpm typecheck | pnpm test:run | pnpm build
docker compose up web      # from the repo root, dev server with the API
```

## API access

The browser only calls `/api/*`. A Next.js rewrite proxies it to `${API_INTERNAL_URL}` (default `http://localhost:8000`, `http://api:8000` in compose), so there is no CORS. RTK Query `baseUrl` is `/api`. Rewrites are baked in at `next build`: for the production image pass `--build-arg API_INTERNAL_URL=...`; `next dev` reads the variable at start.

## Design

`design-system/` is the approved reference (tokens, Mantine theme, specimen); the app copies its tokens and theme into `src/theme/`.

Hero photo: Kumiko Shimizu / Unsplash, https://unsplash.com/photos/white-cloud-sky-lNxMcE8mvIM
