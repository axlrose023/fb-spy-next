# Design Prompt — FB Spy (internal Facebook ad‑intelligence tool)

> Paste this whole file into Claude (design mode). Do not ask me clarifying
> questions — every decision below is final. Make reasonable choices for
> anything unspecified and keep going. Deliver a complete, polished, responsive
> web app design with all screens, states, and components described.

---

## 0. What you are designing

An **internal** web app (no public signup, no marketing, no pricing) used by a
small team to browse Facebook ads that our own crawler harvested. Think of it as
a private "ad library / spy tool": a searchable grid of captured ads, each with
creative imagery, ad copy, advertiser, destination domain, landing URL, UTM
breakdown and one or more screenshots. Plus a thin admin area to manage the few
users who can log in.

It is functionally inspired by **f5spy.com** (a Facebook ad‑spy SaaS): a fil­ter
rail + a card grid of ads + a detail view. **Do not copy its look.** Ours should
feel like a focused, lively internal analytics console — denser and more legible
than f5spy, with crisp whites and punchy accents, clearly *not* the same product.
Same job, better executed. (Light, bright and energetic — never dull or washed‑out.)

Primary goal, in priority order:
1. **Correct, faithful rendering of every ad** — no clipped text, no broken
   images, screenshots shown at the right aspect ratio, every field has a place.
2. **Fast scanning & filtering** of large result sets.
3. **Beauty**: crisp, modern, confident and vivid — comfortable for long working
   sessions, but visually energetic, never flat or dull.

---

## 1. Brand, color, type (fixed — do not deviate toward f5spy)

f5spy uses a **bright, cold blue / white SaaS** look. We must look different —
but we are **light‑theme only**. **Do NOT design a dark theme; no theme toggle.**

**Theme: fresh, modern, light "mint‑green + graphite" analytics console.**
Light and premium, **NOT dull, washed‑out, grey‑on‑grey, or corporate‑blue**.
It should feel fresh, clean and contemporary — bright whites, a confident
mint/emerald green accent, calm graphite text, generous whitespace. Clearly not
f5spy's cold blue. The vibe to aim for: a polished, airy modern web app (think
the clean, spacious feel of high‑end product sites) — current and tasteful, not a
busy legacy admin panel.

- **Primary accent: fresh mint/emerald green.** Use a vivid mint `#3FBF9A` as the
  bright brand green, a deeper emerald `#2E9E73` for primary buttons / strong
  emphasis, and a soft mint tint `#E4F6F0` for selected/active fills and hover
  washes. Green carries the brand — primary actions, active filters, focus rings,
  key counts, "resolved/has‑landing" success. Saturated and confident on white,
  never neon.
- App canvas: clean near‑white with a faint cool‑green undertone `#F5F7F6`
  (bright and fresh, NOT cold blue‑white, NOT beige). Elevated surfaces / cards:
  pure white `#FFFFFF`. Secondary panels (filter rail, sidebar): `#F1F4F2`.
  Hairline borders `#E3E7E5`.
- Text: calm graphite `#28312E` for primary (a soft dark green‑grey, NOT pure
  black, NOT harsh inky black — easy on the eyes), secondary `#5C6661`, muted
  `#8A938E`. High enough contrast to read crisply; never jet‑black, never pale
  washed‑out grey. Headings may go a touch deeper (`#202825`), never `#000`.
- Secondary / contrast accent: deep charcoal‑green `#182628` for occasional
  high‑contrast elements (a dark sidebar option, a dark stat header, the
  wordmark) — used as a tasteful anchor, sparingly, so the app stays light.
- Semantic: success/green `#2E9E73`, warning amber `#E8A93C`, danger coral
  `#E2574C`, info is **not blue‑heavy** — prefer a muted slate `#5B7A86` so we
  stay off the f5spy palette. Bad‑screenshot / error chips use danger.
- Chip fills use clearly visible but soft tints (mint `#E4F6F0`, amber `#FAEFD6`,
  coral `#FBE2DF`, neutral `#ECEFED`) with matching saturated text/border —
  colorful and readable, not faint, not heavy blocks.
- Selected/active states: soft mint fill + green border + green text; hover: a
  light mint/neutral wash (not a barely‑there grey). Use color decisively but
  selectively — on status chips, KPIs, active filters and CTAs — while keeping
  large reading areas (ad copy, tables) clean, white and uncluttered.

**Type:** Inter (or a near‑identical grotesque) for UI; a monospace
(JetBrains Mono / IBM Plex Mono) for technical values — IDs, UTM keys, domains,
URLs, JSON. Tabular numerals for all counts and stats. Generous line‑height in
ad copy, tight in dense tables.

**Shape & depth (MODERN — this matters):** rounded, soft geometry everywhere.
Cards 14–18px radius, inputs/buttons 10–12px, chips/pills fully rounded (999px),
avatars/media tiles 12–16px. **Do NOT make square, sharp‑cornered, boxy
controls** — no 0–2px radius, no hard rectangular buttons, no thick heavy
borders. Buttons are pill‑ish/rounded with comfortable padding, a subtle
press/hover transition, and an optional leading icon — they must look 2025‑modern,
not like an old enterprise form. Soft, low, layered shadows (e.g.
`0 1px 2px rgba(16,40,30,.04), 0 6px 20px rgba(16,40,30,.06)`) for gentle lift on
white; thin 1px borders for structure. Smooth micro‑interactions (hover lifts,
150–200ms ease transitions, gentle focus rings in mint). Aim for a crisp,
contemporary look — rounded, airy, lightly shadowed — explicitly **avoid an
old/dated/sharp/cramped feel.**

**Don't overcrowd — orientation must feel effortless (key requirement):** the
user should always know where they are and find things instantly. Lots of
whitespace; a clear visual hierarchy (one obvious primary action per screen);
generous spacing between groups; never a wall of controls or a cramped toolbar.
Group filters under clear headings, collapse advanced/rarely‑used ones, and keep
the default view simple. Calm, uncluttered, scannable — fewer elements, better
spaced, beats dense and busy. Consistent paddings and alignment on an 8px grid.

**Density:** information‑dense but breathable. This is a power tool, not a
landing page. Default to compact controls with a comfortable‑mode toggle.

---

## 2. Data model the UI renders (this is the real backend — honor it exactly)

The app talks to a FastAPI backend. JSON shapes below are authoritative — every
field must have a designated place (or a deliberate, documented omission).

### 2.1 Ad object (`GET /ads`, `GET /ads/{id}`)

```jsonc
{
  "id": "uuid",
  "run_id": "uuid",                 // which crawl produced it
  "source_index": 4,                // order within the run
  "advertiser": "MINI",            // page/brand name
  "ad_type": "link",               // one of: link | in_facebook | video
  "format": "image",               // one of: image | video   (derived)
  "vertical": null,                 // category — often null today
  "country": null,                  // often null today
  "platform": "facebook",          // always facebook today; design for more
  "placement": "feed",             // feed today; design for more
  "cloaking": null,                 // bool|null — cloaking suspected
  "has_video": true,                // creative contains video
  "displayed_domain": "onlinestore.mini.com.tr",
  "headline": "MINI Countryman",
  "ad_text": "Gerçek MINI deneyimi… (can be long, multi‑paragraph)",
  "cta": "Teklifi Al",            // Learn More / Shop Now / Like Page / …
  "creative_img": "https://scontent.fbcdn.net/…long.jpg",  // remote FB CDN
  "screenshot_path": "imports/run_x/screens/0004_….png",   // local, single (today)
  "screenshot_ok": true,            // bool|null — screenshot QA passed
  "screenshot_issue": null,         // e.g. "blank_media"
  "landing_full": "https://…?utm_source=…&fbclid=…",       // can be VERY long
  "landing_clean": "https://onlinestore.mini.com.tr/test-surusu",
  "landing_screenshot_path": null,  // local, optional
  "fb_ad_id": "1234567890",
  "utm": { "utm_source": "meta", "utm_medium": "cpc", "utm_campaign": "…",
            "utm_id": "…", "utm_content": "…", "utm_term": "…",
            "fbclid": "IwY2x…(very long)" },
  "captured_at": "2026-06-22T13:37:12Z",
  "created_at": "…", "updated_at": "…",
  "screenshot_url": "/media/imports/run_x/screens/0004_….png", // ready to <img>
  "landing_screenshot_url": null                                // ready to <img>
}
```

Field meaning & display rules — **bake these in**:

- **`ad_type`**: `link` = ad pointing to an external landing page;
  `in_facebook` = stays on Facebook (no external landing — landing fields will be
  null, and that is *normal*, not an error); `video` = video ad. Render as a
  small labeled chip with distinct color/icon per type. Never show "missing
  landing" as an error for `in_facebook`.
- **`format`** drives the creative tile: `image` vs `video`. Show a media‑type
  badge on the card.
- **`creative_img`** is the original FB CDN image (may 403/expire over time → must
  have a graceful broken‑image fallback). **`screenshot_url`** is our own captured
  screenshot of the rendered ad (reliable, local). Treat the **screenshot as the
  primary visual** and `creative_img` as secondary/source.
- **`screenshot_ok === false`** or a non‑null **`screenshot_issue`** → show a
  small warning badge ("⚠ blank media", etc.) on the card and a banner on the
  detail. Still show whatever screenshot exists.
- **`landing_full`** can be 500+ chars (UTMs + `fbclid`). Never let it break
  layout: truncate with middle‑ellipsis, full value on hover/expand, one‑click
  copy, and "open in new tab". **`landing_clean`** is the human‑readable link to
  show by default.
- **`utm`** is a dict of arbitrary keys → render as a clean key/value table in
  mono, each value copyable, long values truncated with expand. `fbclid` is huge
  — collapse it by default.
- **`vertical` / `country` / `cloaking`** are frequently `null` today but WILL be
  populated later. Design their chips/filters now; when null, hide the chip on
  the card but keep the filter present (showing an "Unknown"/"—" option).
- **`fb_ad_id`**, **`run_id`**, **`id`**: mono, copyable, truncated.

### 2.2 MEDIA — design for MULTIPLE screenshots and FUTURE video (critical)

Today the API returns **one** `screenshot_url` (+ optional `landing_screenshot_url`).
**But the design must assume an ad can have several media items, and that videos
are coming.** Do not hard‑wire a single image.

Design the detail view around a **media gallery** that takes a normalized list:

```jsonc
"media": [
  { "kind": "screenshot", "type": "image", "url": "/media/…/0004_a.png", "label": "Ad screenshot",      "issue": null },
  { "kind": "screenshot", "type": "image", "url": "/media/…/0004_b.png", "label": "Ad screenshot (2)",  "issue": null },
  { "kind": "landing",    "type": "image", "url": "/media/…/land.png",   "label": "Landing page",       "issue": null },
  { "kind": "creative",   "type": "image", "url": "https://fbcdn…jpg",   "label": "Original creative",  "issue": null },
  { "kind": "video",      "type": "video", "url": "/media/…/0004.mp4",   "poster": "/media/…/0004.png", "label": "Ad video", "issue": null }
]
```

Until the backend sends `media[]`, the frontend **derives** this array from the
current fields (screenshot_url → one screenshot item; landing_screenshot_url →
landing item; creative_img → creative item; if `format==video` later, a video
item). Show this derivation as a tiny adapter note in the spec, but design the UI
purely against `media[]`.

Gallery requirements:
- A **main stage** showing the active item + a **thumbnail strip / carousel**
  below (or left) when there are 2+ items. Keyboard ← / → and swipe on touch.
- **Images**: never crop important content — fit within stage, letterboxed on a
  subtle checker/neutral backing; click to open a full‑screen **lightbox** with
  zoom/pan and a download button. Show natural aspect (FB feed screenshots are
  tall ~9:16/portrait — account for very tall images with internal scroll, not
  page‑breaking).
- **Video**: real `<video>` player with poster, play/pause, scrubber, mute,
  fullscreen, and a "video" badge. When a `video` item exists, it leads the
  gallery.
- **Broken/expired media**: graceful placeholder with the item label + a "source
  may have expired" note; the rest of the gallery still works.
- Each media item shows its `kind` (Screenshot / Landing / Creative / Video) as a
  caption chip, and surfaces `issue` (e.g. blank_media) as a warning.

On the **card** (grid), show only the **primary media** (prefer video poster if a
video exists, else the first screenshot) with a media badge (▶ for video, count
badge like "❏ 3" when multiple) so users know more exists.

### 2.3 List response (pagination envelope — all list endpoints)

```jsonc
{ "items": [ … ], "total": 1234, "page": 1, "page_size": 24,
  "total_pages": 52, "has_next": true, "has_prev": false }
```

Design pagination + result count off these exact fields.

### 2.4 Ad filters / query params (`GET /ads`) — drive the filter rail from these

`run_id`, `ad_type`, `format`, `vertical`, `country`, `platform`, `placement`,
`cloaking` (bool), `has_video` (bool), `screenshot_ok` (bool),
`advertiser__search` (text contains), `displayed_domain__search` (text contains),
`fb_ad_id`, `has_landing` (bool), `q` (free‑text search across copy), plus
`order_by` (default `-captured_at`), `page`, `page_size`.

Map each to a control (see §5). `order_by` options to expose: newest/oldest
captured, advertiser A–Z, domain A–Z.

### 2.5 Stats (`GET /stats/ads`) — drive the dashboard + facet counts

```jsonc
{ "total_ads", "link_ads", "resolved_ads", "video_ads", "bad_screenshots",
  "by_type":[{value,count}], "by_format":[…], "by_vertical":[…],
  "by_country":[…], "by_platform":[…], "by_placement":[…],
  "by_domain":[…], "by_advertiser":[…], "by_cta":[…] }
```

Use the top scalars as KPI tiles and the `by_*` facets as **counts next to each
filter option** and as the dashboard's "top advertisers / top domains / by type /
by CTA" widgets. (Note the f5spy nuance we improve on: filters should always show
**live result counts**, and selecting filters should visibly narrow those
counts.)

### 2.6 No "Runs" section (important)

The crawler is conceived as **always‑on** — it just keeps collecting ads in the
background, forever. **Do NOT design any Runs / crawl‑management section, list,
detail, "start run" form, or import UI.** There is no operator screen for
sessions. `run_id` still exists on each ad (which batch produced it) and may be
shown as a small technical/meta value on the ad detail and used as an internal
filter, but it is **not** a navigable section and there is no run management in
the product. Treat the data as one continuously growing library of ads.

### 2.7 Auth & Users

- **Auth**: `POST /auth/login {username,password}` → `{access_token,
  refresh_token, token_type, expires_in, refresh_expires_in}`. `POST
  /auth/refresh`. **No registration screen at all.** Bearer token on every call.
- **Current user**: `GET /users/me` → `{id, username, role, is_active}` where
  `role ∈ {admin, user}`.
- **Users admin** (admin‑only): `GET /users` (paginated, filter by username /
  role), `POST /users {username,password,role}`, `PATCH /users/{id}
  {username?,password?,role?,is_active?}`.
- **Permission rules to reflect in UI**:
  - Only **admin** sees the Users section and the "Create user" button.
  - A **regular user** can edit **only their own** account, and **cannot** change
    their own `role` or `is_active` (hide/disable those controls for them).
  - Admin can edit anyone, including role and active status.
  - `409` on duplicate username → inline "username already taken".

---

## 3. Information architecture / navigation

Persistent **left sidebar** (collapsible to icons) + **top bar**.

Keep navigation minimal — only three destinations. Sidebar nav (role‑aware):
- **Ad Library** (default landing) — the grid + filters. The heart of the app.
- **Dashboard** — KPIs + facet widgets from `/stats/ads`.
- **Users** — *admin only*.
- Footer of sidebar: current user (avatar/initials, username, role pill),
  logout. (No theme toggle — the app is light‑theme only.) **No "Runs" item.**

Top bar: global **search box** (binds to `q`), active‑filters summary, result
count, and density toggle. (No "start run" action — the crawler runs on its own.)

Routes (for the spec): `/login`, `/` (Ad Library), `/ads/:id` (detail, also works
as a right‑side drawer over the grid), `/dashboard`, `/users` (admin), plus a
`/403` and `/404`. (No `/runs` routes.)

---

## 4. Screens to deliver (design ALL of these, with all states)

### 4.1 Login
- Centered card on a fresh branded background (subtle light mint→white gradient,
  faint grid or soft organic shapes — NOT f5spy's bright blue hero). App
  name/logo (design a simple modern wordmark "FB SPY" / a small radar/eye glyph
  in mint‑green).
- Fields: username, password (show/hide), a rounded "Sign in" button in green.
  Inline error for bad credentials (401). Loading state on the button. No
  "sign up", no "forgot password" link (internal tool) — but show a small
  "Contact your admin" hint.

### 4.2 Ad Library (primary screen) — design this most carefully
Three‑pane feel: **filter rail (left)** · **results grid (center)** · optional
**detail drawer (right)**.

- **Filter rail** (collapsible): grouped controls (see §5) with live facet
  counts; an "active filters" chip bar at the top of results showing each applied
  filter as a removable pill + "Clear all". Sticky.
- **Results header**: result count ("1,234 ads"), `order_by` dropdown, density
  toggle, grid/list view toggle, and the saved/active‑filter pills.
- **Card grid** (responsive: 2→3→4→5 cols by width). Each ad card:
  - Primary media thumbnail (screenshot; video poster if video) at correct
    aspect (cards in a masonry OR fixed‑ratio grid — pick fixed 4:5 tiles with
    object‑fit that letterboxes tall screenshots gracefully; show full image on
    hover/zoom). Media badges: ▶ video, "❏ N" multi‑media, ⚠ bad‑screenshot.
  - Advertiser (bold) + small avatar/monogram. `ad_type` chip. `cta` pill.
  - Headline (1 line, ellipsis). Ad text (2 lines, ellipsis).
  - Footer: `displayed_domain` (mono, truncated, link icon), captured‑at relative
    time ("2d ago"), and a "has landing"/green dot when resolved.
  - Hover: subtle lift + quick actions (open detail, copy landing, open landing).
- **List view** alternative: dense table (media thumb, advertiser, type, domain,
  CTA, captured, status) for power scanning.
- **States**: loading skeleton cards; empty state ("No ads match these filters" +
  Clear filters); error state with retry; end‑of‑list. Pagination control (page
  numbers + prev/next) bound to the envelope; consider infinite scroll as the
  default with a "load more" fallback.

### 4.3 Ad Detail (full page AND right‑drawer variants)
Two‑column layout:
- **Left**: the **media gallery** (§2.2) — main stage + thumbnail strip,
  lightbox, video player, broken‑media fallback, issue banners.
- **Right**: structured facts:
  - Advertiser block (name, monogram, `ad_type`, `platform`, `placement`,
    `country`/`vertical` chips when present).
  - **Headline** (prominent) + **full ad text** (selectable, preserves
    line breaks, scrolls within a max height, "show more").
  - **CTA** pill.
  - **Destination** panel: `landing_clean` as the primary clickable link;
    expandable `landing_full` with middle‑ellipsis, copy, open‑new‑tab;
    `displayed_domain`.
  - **UTM table**: key/value mono rows, each copyable, long values + `fbclid`
    collapsed by default.
  - **Technical** panel: `fb_ad_id`, `id`, `run_id` (shown as a plain copyable
    meta value — NOT a link, there is no runs section),
    `captured_at` (absolute + relative), `screenshot_ok`/`issue` status.
- Header actions: copy link to this ad, open landing, prev/next ad (← →) within
  the current filtered result set, close (drawer).
- Warning banner when `screenshot_ok===false` or `cloaking===true` (a "possible
  cloaking" warning banner in amber).

### 4.4 Dashboard
- Top row KPI tiles (tabular nums, sparkline optional): Total ads, Link ads,
  Resolved (with landing), Video ads, Bad screenshots — each clickable to jump to
  the Library pre‑filtered.
- Facet widgets from `by_*`: "Top advertisers", "Top domains", "By ad type",
  "By CTA", "By format" — horizontal bar lists with counts; clicking a row
  applies that filter in the Library.
- Make KPIs and facet bars colorful and lively (saturated mint/green accents,
  bold tabular numbers) so the dashboard feels vibrant at a glance — clear and
  scannable, with lots of breathing room; not a busy BI cockpit, but definitely
  not grey and flat.

### 4.5 Users (admin only)
- **Users table**: username (mono), role pill (admin=green, user=neutral),
  active toggle, created date; row → edit. "Create user" primary button (admin
  only).
- **Create / Edit user drawer**: username, password (create: required;
  edit: optional "set new password"), role select (admin/user), active toggle.
  - For a **regular user editing themselves** (reachable via "My account"): same
    drawer but role + active are **hidden/disabled**; only username + password.
  - Inline `409` duplicate‑username error; success toast.
- **My account** entry (all roles) in the user menu → opens the self‑edit drawer.

### 4.6 System states
- 401 (token expired) → silent refresh; on failure, bounce to /login with a
  toast. 403 page for non‑admins hitting admin routes. 404 page. Global toast
  system for success/error. Offline/refetch banners.

---

## 5. Filter rail — exact controls (improve on f5spy)

Group and label clearly; each option shows a **live count** from facets; multiple
filters combine (AND); everything reflects in URL query params (shareable links);
"Clear all" resets.

- **Search** (`q`): big text input, debounced, searches ad copy/headline.
- **Ad type** (`ad_type`): segmented/checkbox chips — Link / In‑Facebook / Video
  (with counts).
- **Format** (`format`): Image / Video toggle.
- **Has video** (`has_video`): toggle.
- **Advertiser** (`advertiser__search`): text contains, with type‑ahead from
  `by_advertiser` facet.
- **Domain** (`displayed_domain__search`): text contains, type‑ahead from
  `by_domain`.
- **Has landing** (`has_landing`): toggle (Resolved / All / No landing).
- **Screenshot quality** (`screenshot_ok`): All / OK / Problem.
- **Cloaking** (`cloaking`): Any / Suspected / Clean (often null → "Unknown").
- **Country** (`country`) & **Vertical** (`vertical`): dropdowns; show "Unknown"
  bucket while mostly null, but keep them — they fill in later.
- **Platform** (`platform`) & **Placement** (`placement`): dropdowns (facebook /
  feed today; design for more values).
- **FB Ad ID** (`fb_ad_id`): exact‑match input.
  (Note: the API also accepts `run_id`, but since there is no runs section, do
  NOT surface a "run" filter in the UI — treat it as internal only.)
- **Sort** (`order_by`): Newest / Oldest captured · Advertiser A–Z · Domain A–Z.

f5spy nuances we explicitly fix: (a) filters always show **result counts**;
(b) applied filters are **visible, removable pills**; (c) state lives in the
**URL** so a filtered view is shareable/bookmarkable; (d) the grid never breaks on
long domains/URLs/ad text; (e) tall portrait screenshots render fully, never
cropped to mush.

---

## 6. Components to define in the design system

Buttons (primary green / secondary outline / ghost / danger — all rounded, never
square), inputs, selects,
multi‑select with counts, segmented controls, chips/pills (filter, status, type,
CTA, role), toggle switches, KPI tile, ad **card** (grid + list variants),
**media gallery** (stage, thumb strip, lightbox, video player, broken/empty),
key/value mono table (UTM), copyable mono field with truncation, long‑URL field
(middle‑ellipsis + copy + open), pagination, result‑count header, active‑filter
bar, sidebar nav item (with count badges), top bar, drawer, modal, toast,
skeletons, empty states, error states, status chips, role pills, avatar/monogram,
tooltip. Provide hover/focus/active/disabled/loading for each, and
**visible keyboard focus rings** (mint‑green) — accessibility matters.

---

## 7. Interaction & quality bar

- **Responsive**: graceful from ~1440px down to tablet; sidebar collapses; grid
  reflows 5→2 cols; filter rail becomes a slide‑over on narrow widths.
- **Keyboard**: arrow keys move between ads in grid/detail; `/` focuses search;
  `Esc` closes drawer/lightbox; tab order sane.
- **Performance feel**: skeletons, optimistic toggles, debounced search,
  lazy‑loaded media, no layout shift when images load (reserve aspect boxes).
- **Copy everywhere**: IDs, domains, URLs, UTM values — one‑click copy with a
  "copied" tick.
- **Truncation discipline**: every potentially long string (ad_text, headline,
  landing_full, fbclid, domain) has a defined truncate + reveal behavior; nothing
  ever overflows a card or breaks the grid.
- **Empty/null grace**: null vertical/country/cloaking/landing render as quiet
  "—", never as errors (except real screenshot issues).

---

## 8. Deliverables

1. A cohesive **design system** page (colors, type scale, spacing, radii,
   shadows, all components with states) — **light theme only**.
2. **All screens** in §4, each in default / loading / empty / error states (light
   theme): Login, Ad Library (grid + list, with filter rail and active‑filter
   bar), Ad Detail (full page + drawer, with the multi‑item media gallery and a
   video example), Dashboard, Users (table + create/edit drawer), My‑account
   self‑edit, plus 403 / 404 / global toasts. (No Runs screens — there is no runs
   section.)
3. Responsive variants (desktop‑wide, laptop, tablet) for Ad Library and Ad
   Detail at minimum.
4. The **media gallery** spec'd explicitly for: 1 screenshot, multiple
   screenshots, screenshot + landing + creative, and a video item — proving the
   layout scales from one image today to mixed media + video tomorrow.

Make it genuinely beautiful, modern and obviously **not** f5spy: a fresh light
canvas (NOT cold blue‑white), mint/emerald‑green accents, soft graphite text (not
harsh black), mono technical fields, rounded contemporary controls (never square
or dated), generous whitespace and effortless orientation (never overcrowded),
bright and lively (never dull or washed‑out), with flawless handling of
long text, tall screenshots, broken
media, and multi‑/future‑video assets. Light theme only — no dark mode.
Proceed end‑to‑end without asking me to choose anything.
```
