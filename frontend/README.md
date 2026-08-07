# FB Spy — Frontend

Real, data-driven React app for the FB Spy ad-intelligence console. It is a **faithful 1:1 port of the approved `.dc.html` mockup** — same colours, type (Inter + JetBrains Mono), spacing, radii, shadows, screens, sections and wording — with the mockup's placeholders replaced by real state, props and live API data.

## Stack
- React 18 + TypeScript + Vite
- React Router (URL-driven filters/pagination/sort)
- TanStack Query (React Query) for server state
- axios API client with JWT auth + single-flight refresh
- Light theme only (no dark mode / toggle), exactly as the mockup

## Project layout
```
frontend/
├─ Dockerfile            multi-stage: node build → nginx serve
├─ nginx.conf           /api/ + /media/ proxy to backend, SPA fallback
├─ .env.example         VITE_API_BASE_URL=/api
├─ index.html           loads Inter + JetBrains Mono
└─ src/
   ├─ main.tsx          providers (QueryClient, Router, Toasts, Auth)
   ├─ App.tsx           routes + RequireAuth / RequireAdmin guards
   ├─ index.css         global reset + keyframes + scrollbar (from mockup helmet)
   ├─ theme.ts          PAL palette + reusable inline-style helpers (verbatim values)
   ├─ auth.tsx          AuthProvider / useAuth (login, logout, current user)
   ├─ toasts.tsx        global toast system + useCopy()
   ├─ useUrlFilters.ts  AdFilters <-> URL querystring (shareable views) + active pills
   ├─ api/
   │  ├─ types.ts       Ad, Page<T>, AdStats, User, AdFilters, MediaItem …
   │  ├─ client.ts      axios instance, token store, refresh, endpoints, param builder
   │  └─ hooks.ts       useMe, useAds, useAd, useStats, useUsers, mutations
   ├─ lib/media.ts      buildMedia() adapter, primaryMedia, rel/abs/mono/midEllipsis
   ├─ components/
   │  ├─ Shell.tsx          sidebar + top bar + self-account drawer
   │  ├─ FilterRail.tsx     grouped filters with live facet counts
   │  ├─ AdCard.tsx         grid card (real screenshot, badges, quick actions)
   │  ├─ AdDetail.tsx       media gallery + lightbox + UTM/technical panels
   │  ├─ UserDrawer.tsx     create / edit / self-edit user
   │  ├─ SafeImage.tsx      graceful broken/expired-image fallback
   │  └─ DebouncedInput.tsx debounced text input for URL-bound filters
   └─ pages/
      ├─ Login.tsx        AdLibrary = Library.tsx, AdDetailPage.tsx, Users.tsx, Misc.tsx (403/404)
```

## Local development
```bash
cd frontend
cp .env.example .env
npm install
npm run dev          # http://localhost:5173
```
In dev, Vite proxies `/api` and `/media` to the backend (default `http://localhost:8000`; override with `VITE_DEV_BACKEND`).

## Production build
```bash
npm run build        # type-checks then builds to dist/
```

## Docker
Multi-stage `Dockerfile` builds the app and serves it with nginx. `nginx.conf` proxies `/api/` and `/media/` to the existing FastAPI `app` service over the docker network and adds an SPA fallback so client routes survive reloads.

The root `compose.yml` already includes the frontend service:
```yaml
services:
  frontend:
    build:
      context: ./frontend
      args:
        VITE_API_BASE_URL: /api
    ports:
      - "${FRONTEND_PORT:-8080}:80"
    depends_on:
      app:
        condition: service_healthy
```
The app runs same-origin, so `VITE_API_BASE_URL=/api` and there is **no CORS**.

## How it maps to the backend
- **Auth** — `POST /auth/login` stores `{access_token, refresh_token}` in localStorage; `Authorization: Bearer` on every request. On `401` the client tries `POST /auth/refresh` **once** (single-flight, concurrent requests queue behind it); on failure it clears tokens and redirects to `/login`. `GET /users/me` gates admin-only UI (Users section + Create user).
- **Ads** — `GET /ads` driven entirely by the URL querystring (`q`, `ad_type`, `format`, `has_landing`, `screenshot_ok`, `cloaking`, `advertiser__search`, `displayed_domain__search`, `fb_ad_id`, `country`, `vertical`, `placement`, `order_by`, `page`, `page_size`). The pagination envelope (`total/page/total_pages/has_next/has_prev`) feeds the pager. `GET /ads/{id}` powers the full-page detail; the drawer reuses the list item.
- **Stats** — `GET /stats/ads` feeds the **filter facet counts** (by_type, by_format, by_advertiser, by_domain, by_country, by_vertical, by_placement) and the Has-landing / Screenshot-quality counts.
- **Users** — `GET /users` (role filter), `POST /users`, `PATCH /users/{id}`. Regular users edit only themselves and cannot change their own role/active status (hidden); a `409` duplicate username shows an inline error.
- **No Runs section.** `run_id` is shown read-only in the ad's Technical panel.

## Media gallery (future-proof)
`lib/media.ts#buildMedia(ad)` derives a normalised `MediaItem[]` from the current fields — `screenshot_url → screenshot`, `landing_screenshot_url → landing`, `creative_img → creative`, and `format === "video" → a video item` (poster for now). The gallery (stage + thumbnail strip + lightbox + video player) is written purely against this array, so when the backend starts returning multiple screenshots or real video URLs, no redesign is needed. `screenshot_url`/`landing_screenshot_url` are `/media/...` paths used directly in `<img>`; `creative_img` (remote FB CDN, can 403) uses the `SafeImage` broken-image fallback. Tall portrait screenshots are letterboxed and scroll inside the stage / lightbox — never cropped to mush.
```
