# FB Spy API

Internal Facebook ads spy backend built from `base_project_template_with_browser_automation`.

The product shape follows the useful base of f5spy-style ad libraries: searchable ads, filters/facets, ad detail viewer, and local media. It intentionally excludes SaaS pieces such as pricing, subscriptions, unlock flows, teams, billing, and public accounts.

## Core API

### Ads Library

`GET /ads`

Main feed for future frontend. Supports pagination and filters:

- `page`, `page_size`
- `q` full-text-ish search over advertiser/domain/headline/text/CTA/landing
- `run_id`
- `ad_type`: `link`, `video`, `in_facebook`
- `format`: `image`, `video`
- `vertical`: future manual/LLM classification, e.g. `crypt`, `gambling`, `nutra`, `news`, `product`
- `country`: future proxy/profile country
- `platform`: default `facebook`
- `placement`: default `feed`
- `cloaking`: future manual/LLM flag
- `has_video`, `has_landing`, `screenshot_ok`
- `advertiser__search`, `displayed_domain__search`, `fb_ad_id`
- `order_by`, default `-captured_at`

`GET /ads/{ad_id}`

Ad detail: advertiser, text, domain, CTA, creative URL, FB screenshot URL, landing URL, UTM, fb_ad_id, screenshot quality flags.

### Runs

`POST /runs`

Starts the existing Facebook runner as a subprocess. Current runner is intentionally kept as a single file at `src/app/services/facebook_runner.py`.

```json
{
  "title": "10 min debug",
  "minutes": 10,
  "resolve_max": 200,
  "debug": true
}
```

`POST /runs/{run_id}/stop`

Temporary stop endpoint while the collector is not daemonized forever.

`GET /runs`, `GET /runs/{run_id}`

Run status, process pid, log path, result counters.

`POST /runs/import`

Imports an existing `ads.json`. If the run is outside `storage/facebook`, `ads.json`, optional `run_meta.json`, and media folders (`screens`, `videos`, `landing_screens`, `landing_archives`) are staged locally.

```json
{
  "ads_json_path": "/absolute/path/to/fb_spy/results/run_20260622_163639/ads.json",
  "title": "old debug run"
}
```

### Stats / Facets

`GET /stats/ads`

Counters and top facets for filters: type, format, vertical, country, platform, placement, domain, advertiser, CTA.

### Media

`GET|HEAD /media/ads/{ad_id}/{kind}?token=...`

Protected backend delivery for ad screenshots, full-page landing screenshots,
videos, and landing ZIP archives. Ad list/detail responses expose only signed
same-origin backend URLs. S3 endpoint, bucket, credentials, object keys, and
database storage markers are never part of the public schema. The URL token is
bound to the ad ID and media kind and defaults to a 30-day lifetime. Video
requests support a single HTTP byte range.

Ads, runs, and stats endpoints require a bearer access token. Starting,
stopping, and importing runs requires an admin account.

## Setup

```bash
uv sync
cp .env.sample .env
uv run cli upgrade
uv run app
```

## Protected S3 Media

Set the `APP__MEDIA__*` variables documented in `.env.sample` only in the
backend environment. Configure the storage provider's independent read-only
credential in `APP__MEDIA__READ_ONLY_SECRET_ACCESS_KEY`; downloads use that
credential while uploads and maintenance use the write credential. Use a
separate random signing secret and never reuse either storage secret. A
production process refuses to start with the development signing key, a weak
JWT key, a missing/shared read-only key, a non-HTTPS S3 endpoint, or an endpoint
containing credentials, path, query, or fragment.

Objects use deterministic keys under a configurable prefix:

```text
ads/{ad_uuid}/screenshots/feed.png
ads/{ad_uuid}/screenshots/landing-full.png
ads/{ad_uuid}/videos/creative.mp4
ads/{ad_uuid}/archives/landing.zip
```

New imports upload available media automatically and verify the remote object
size before replacing local database paths with internal `s3:` markers. Local
source files are retained as a recovery copy. Uploads larger than 100 MB use
multipart transfer; upload and part concurrency are independently bounded.

Migrate existing database records in committed batches:

```bash
uv run cli sync-facebook-media --batch-size 50
uv run cli sync-facebook-media --run-id RUN_UUID
uv run cli sync-facebook-media --ad-id AD_UUID
```

The command is idempotent: media fields already stored as S3 markers are
skipped. Test a bounded subset with `--limit` before a full migration.

## Import Previous Run

```bash
curl -X POST http://localhost:8000/runs/import \
  -H 'Content-Type: application/json' \
  -d '{"ads_json_path":"/Users/axlrose023/PycharmProjects/youtube_automation/fb_spy/results/run_20260622_163639/ads.json","title":"run_20260622_163639"}'
```

## Start Collector

Octo Browser Local API and profile proxy must be healthy first.

```bash
curl -X POST http://localhost:8000/runs \
  -H 'Content-Type: application/json' \
  -d '{"title":"10 min", "minutes":10, "resolve_max":200, "debug":true}'
```

To bind a run to a specific Octo profile, pass `octo_profile_uuid`. If omitted,
the configured `APP__FACEBOOK__OCTO_PROFILE_UUID` is used.

Runner output is stored under `storage/facebook/runs` and imported into PostgreSQL when the process exits.

## Manual Profile Calibration

Calibration is a profile-bound pass over previously accepted relevant ads. It
never discovers or reclassifies ads. On desktop-capable profiles it reopens the
saved Facebook post, views it, applies bounded likes/follows, and continues via
the ad CTA. If the post cannot be rendered on a mobile profile, it falls back to
the saved full offer URL. In both cases the offer stays in the same Octo context,
the prelander is scrolled, supported quizzes are completed, and a detected lead
form is reported separately from a confirmed registration. Relevant landing-only
records are valid calibration targets.

Form submission defaults to `disabled`. `fill_only` fills an explicitly supplied
test identity without submitting. `allowlisted` can submit only when both an
exact/subdomain allowlist and a private identity file are configured. Password,
file, payment, banking, passport, tax and similar fields stop form handling.
One target can be submitted at most once per calibration process, and a click is
not counted as a confirmed registration until a success URL or message appears.
Offer tabs remain open during the calibration approach and are closed when its
Octo session ends. Comments remain disabled by the production defaults.

Use a previously classified relevant-ad file:

```bash
uv run facebook-spy calibrate \
  --octo-profile-uuid "OCTO_PROFILE_UUID" \
  --ads-json storage/facebook/runs/run_x/ads.relevant.json \
  --limit 20 \
  --view-seconds 45 \
  --offer-funnel \
  --session-minutes 15 \
  --repeat-targets-until-deadline
```

Multiple saved relevant-ad files can be supplied:

```bash
uv run facebook-spy calibrate \
  --octo-profile-uuid "OCTO_PROFILE_UUID" \
  --country "Turkey" \
  --ads-json storage/facebook/runs/run_x/ads.relevant.json \
  --limit 20
```

Outputs are written to `storage/facebook/calibration/calibration_*`:
`run_meta.json`, `targets.json`, `events.jsonl`, `results.json`, `summary.json`,
and optional screenshots. These artifacts are private (`0600`); public event
payloads contain landing domains and redacted URLs rather than offer query data.

Authorized end-to-end submission requires explicit configuration:

```bash
FACEBOOK_CALIBRATION_OFFER_SUBMIT_MODE=allowlisted
FACEBOOK_CALIBRATION_OFFER_SUBMIT_ALLOW_DOMAINS=qa-offer.example
FACEBOOK_CALIBRATION_OFFER_IDENTITY_JSON=storage/facebook/orchestrator/offer-identities.json
```

The identity file accepts a flat identity or profile/country-specific records:

```json
{
  "profiles": {
    "OCTO_PROFILE_UUID": {
      "first_name": "QA",
      "last_name": "User",
      "email": "qa@example.test",
      "phone": "+12025550123",
      "country_code": "CA"
    }
  },
  "countries": {},
  "default": {}
}
```

## Profile Orchestrator

The orchestrator is a CLI-only layer over the existing collector and calibrator.
It does not change the backend API or frontend. One Octo profile is treated as
one independent geo worker.

Create `storage/facebook/orchestrator/profiles.json`:

```json
{
  "profiles": [
    {
      "octo_profile_uuid": "282c4c93625740239ad7261235bd088b",
      "label": "spain",
      "expected_country": "Spain",
      "enabled": true,
      "calibration_ads_json": [
        "storage/facebook/manual_parallel_20260709_141130/collect_spain/ads.json"
      ]
    },
    {
      "octo_profile_uuid": "replace-with-octo-profile-uuid",
      "label": "turkey",
      "expected_country": "Turkey",
      "enabled": true,
      "no_country_filter": true,
      "calibration_ads_json": [
        "storage/facebook/imports/relevant_only_20260625/ads.json"
      ]
    },
    {
      "octo_profile_uuid": "replace-with-profile-uuid",
      "label": "dominican_republic",
      "expected_country": "Dominican Republic",
      "enabled": true,
      "quality_guard": true,
      "failed_recovery_calibration_passes": 2,
      "no_country_filter": true,
      "calibration_ads_json": [
        "storage/facebook/orchestrator/calibration_pools/spain.json",
        "storage/facebook/orchestrator/calibration_pools/argentina.json"
      ]
    }
  ]
}
```

`quality_guard` promotes the first full healthy relevance run to a trusted
profile baseline. A later single-window drop calibrates only when at least two
independent relevance signals decline. During active recovery,
`failed_recovery_calibration_passes: 2` allows a second immediate pass over
previously unused saved posts when the validation run did not meaningfully
improve.

Each profile keeps `calibration_target_health.json` next to its calibration
pool. A direct Facebook post is quarantined for seven days after two confirmed
`post_not_found` results and is retried after the quarantine expires. A later
successful open clears its failure record. The shared geo pool is left intact,
so one account cannot suppress a target for other profiles.

Seed the current farmed Spain profile as a baseline:

```bash
uv run python -m app.services.facebook_orchestrator seed-baseline \
  --profile-uuid 282c4c93625740239ad7261235bd088b \
  --label spain \
  --expected-country Spain \
  --run-dir storage/facebook/manual_parallel_20260709_141130/collect_spain \
  --default-elapsed-seconds 900
```

Run one cycle for all enabled profiles in parallel:

```bash
uv run python -m app.services.facebook_orchestrator run \
  --profiles-json storage/facebook/orchestrator/profiles.json \
  --octo-host 127.0.0.1 \
  --octo-port 58888 \
  --max-parallel 2 \
  --collect-minutes 15
```

The orchestrator passes collection-safe defaults to the runner:

- `--interest-safe-collection`: the authenticated profile only observes feed
  cards; it does not click CTAs/comments or intentionally play ad videos.
  A pre-navigation script rejects `play()` calls and a page-level route blocks
  video media requests before Facebook renders the feed;
- a passive relevance prefilter writes `ads.prefilter.json` and assigns every
  card to `allow`, `deny`, or `hold`;
- a `hold` card is checked in a one-use browser context with zero Facebook
  cookies. A passive external CTA URL is preferred. When mobile Facebook hides
  the URL, the resolver opens the saved direct post anonymously, locates the
  exact advertiser/CTA card, and follows only that CTA. Private-network targets
  and Meta tracking from the external landing are blocked. The context is
  destroyed after one card, and the second gate is written to `ads.gated.json`;
- only `allow` rows enter the enrichment stage, which reopens the saved direct
  Facebook post and captures its video/landing. Denied or unresolved rows cannot
  start authenticated profile actions;
- the persistent profile page is paused, closed down to one tab, and navigated
  to `about:blank` before model classification and after active enrichment;
- `--max-ads-per-view 1`: process one new ad, then scroll again;
- `--video-max-seconds 10`: short creative capture instead of long video
  recording per ad;
- `--landing-archive-timeout 12` and `--landing-archive-max-resources 80`;
- hard per-ad landing and video deadlines; if a CDP call itself hangs, the
  already captured ad is saved and the cycle ends as `resolve_timeout` or
  `video_timeout` so the orchestrator can restart a clean browser session;
- `--collect-timeout-grace 180`: if a collector exceeds `collect-minutes`
  plus grace, the orchestrator sends SIGINT so the run can write `summary.json`,
  then terminates it if needed.

Override these flags per run when doing a deeper manual capture.

Run continuously:

```bash
uv run python -m app.services.facebook_orchestrator run \
  --profiles-json storage/facebook/orchestrator/profiles.json \
  --octo-host 127.0.0.1 \
  --octo-port 58888 \
  --max-parallel 5 \
  --collect-minutes 15 \
  --profile-rest-minutes 15 \
  --loop
```

For the optional production Compose service, set an Octo host reachable as
`APP__FACEBOOK__OCTO_HOST`, then start only its profile. Existing entries in
`profiles.json` can run without a Public API token. Set
`APP__FACEBOOK__OCTO_API_TOKEN` and `APP__FACEBOOK__OCTO_SEARCH_TAGS` to enable
automatic discovery of newly added Octo profiles:

```bash
docker compose -f compose.prod.yml --profile facebook-orchestrator \
  up -d facebook-orchestrator
```

The Octo Client must be running and logged in on the reachable host, and its
dynamic CDP ports must be reachable from the container. Browser mode follows
`APP__FACEBOOK__OCTO_HEADLESS` (`false` by default). Visible and headless runs
keep separate baselines because their feed yield can differ.

On a Linux host, keep the Octo Local API and random CDP ports reachable from
Docker but closed to the public network:

```bash
sudo install -m 0755 deploy/restrict-octo-api /usr/local/sbin/restrict-octo-api
sudo install -m 0644 deploy/restrict-octo-api.service \
  /etc/systemd/system/restrict-octo-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now restrict-octo-api.service
```

The service allows loopback and Docker bridge traffic, then drops external
connections to the Local API on `58888` and Octo's dynamic CDP range. The base
Compose file also binds PostgreSQL, Redis, the direct app/frontend ports, and
monitoring ports to `127.0.0.1`; only the reverse proxy should be public.

Continuous mode has no global round barrier. When one profile finishes its
collection and optional calibration, only that profile rests. The delay is the
larger of `--profile-rest-minutes` and `--cycle-sleep`. With the production
defaults (`max-parallel=5`, 15-minute collection, 45-minute rest), up to five
geos work at once while due profiles are selected in oldest-due order. With ten
similarly paced profiles this naturally alternates two groups of five; a slow
or failed profile does not delay another profile. `SIGINT`/`SIGTERM` is
forwarded to active child processes so collector summaries can be finalized
before shutdown. After collection and optional calibration complete, the Octo
profile itself is stopped before its rest window, so idle geos do not consume a
browser slot or retain Chromium memory.

Low-quality results use a separate per-profile recovery schedule. A completed
recovery calibration is followed immediately by another collection, and the
profile repeats `collect -> evaluate -> calibrate` up to
`--recovery-burst-cycles` times (three by default). Recovery ends as soon as a
validation collection is healthy. If all three attempts remain below the
configured relevance thresholds, the profile takes the normal 45-minute rest
and starts a new bounded burst afterward. Octo/proxy failures do not consume a
recovery attempt and use `--infrastructure-retry-minutes` instead. Burst state
and the pending rest type are persisted per Octo UUID, so container restarts do
not reset the backoff or couple one geo to another.

To make Octo the source of new profiles, add a dedicated Octo tag to FB
profiles and run discovery through the Public Automation API. Octo's Public API
uses `GET /profiles` with the `X-Octo-Api-Token` header; Local API can only
reliably expose active profiles.

```bash
# These can also be set as APP__FACEBOOK__OCTO_API_TOKEN and
# APP__FACEBOOK__OCTO_SEARCH_TAGS in .env.
export OCTO_API_TOKEN="..."

uv run python -m app.services.facebook_orchestrator run \
  --profiles-json storage/facebook/orchestrator/profiles.json \
  --discover-octo-profiles \
  --octo-search-tags "OCTO_TAG_UUID" \
  --enable-discovered \
  --max-parallel 5 \
  --collect-minutes 15 \
  --profile-rest-minutes 15 \
  --loop
```

Newly discovered profiles are keyed only by Octo UUID. Geo is still verified
from the running profile connection data before health decisions are trusted.
If the Public API profile has no country hint, the first successful profile
start adopts and persists the observed country in `profiles.json`. Missing or
mismatched geo blocks both baseline updates and calibration.

Each profile is locked by UUID, so a profile never collects and calibrates at
the same time. One collection result may trigger a bounded recovery burst of
calibration passes, but the same profile remains serial throughout that cycle.
Other profiles keep working in parallel.

Browser-captured landing ZIP files use an offline `index.html` preview backed
by the captured screenshot. The raw browser DOM and complete MHTML snapshot are
kept under `browser/`, and `manifest.json` identifies the capture format. This
avoids making the ZIP entry page depend on assets that may later disappear or
reject an offline browser session.

When `APP__FACEBOOK__RELEVANCE_FILTER_ENABLED=true` (or
`--classify-relevance` is passed), each completed collection is classified with
the existing Gemini relevance filter before health evaluation. Raw `ads.json`
is preserved. Interest-safe runs additionally write `prefilter_summary.json`,
`isolated_resolution_summary.json`, `gate_summary.json`, and
`enrichment_summary.json`. Final classification writes `ads.classified.json`,
`ads.relevant.json`, `ads.not_relevant.json`, and `relevance_summary.json`.
The summaries include active-action counters and fail closed if an action ever
reaches a blocked row.

Pass `--import-backend` to create an API run from the completed classified
cycle. The production Compose orchestrator enables this by default and imports
`ads.relevant.json` with relevance filtering disabled for that import, so
Gemini is not called twice. Import is idempotent by `runner_run_dir`; restarting
the orchestrator cannot duplicate a completed run in the database.

Health decisions are written next to each collection run as `health.json`.
The state is stored in `storage/facebook/orchestrator/state.json`.

Calibration is considered when the issue looks like account/feed quality, not
infrastructure. Throughput metrics require a complete observation window;
relevance metrics may accumulate classified ads from shorter runs:

- repeated zero ads;
- no more than 12 ads/hour (three ads per 15-minute window) for two complete
  windows, even while the profile is still learning its personal baseline;
- severe `ads_per_hour` collapse below 45% of a mature profile baseline for
  repeated windows;
- severe `ads_per_100_scrolls` collapse below 45% of a mature profile baseline
  for repeated windows;
- a 30% or larger drop in ad yield or relevant-ad yield from a mature baseline
  in one valid window;
- a sustained softer drop below 95% of baseline for two complete windows in
  production,
  when both hourly yield and yield per 100 scrolls agree;
- if relevance filtering is enabled, any otherwise valid classified run below
  75% relevant ads or below 15 relevant ads triggers calibration immediately,
  without waiting for or comparing against a profile baseline;
- once the current run has at least 15 relevant ads and is at least 75% relevant,
  `relevant_ads_per_hour` and `relevant_rate` can be compared with the healthy
  profile baseline to detect a gradual decline;
- periodic account maintenance after three hours without an effective
  calibration and at least two nonzero classified observation windows in
  production.

Mature baseline normally means at least 3 good windows for that Octo profile.
An explicitly seeded, operator-confirmed reference is marked `trusted` and can
be used immediately for the same window duration. A softer drop first becomes
`watch`; in production it becomes a calibration reason after two consecutive
valid windows. The soft signal has no additional absolute-delta gate: both
hourly yield and yield per 100 scrolls must independently fall below 95%, which
keeps a single noisy metric from triggering it. Severe drops still require two
valid windows.

Ad-volume and relevance baselines are kept separate. A legacy
`resolved_landings` baseline is never compared with a classified relevance
rate. Once a baseline is mature, degraded/watch windows are not allowed to drag
the reference downward; only healthy windows can refresh it.

Relevance results below the absolute benchmark do not use statistical
comparison: `2/20`, `1/36`, `0/N`, and even `10/10` all calibrate directly.
Baseline comparison starts only at 15 relevant ads and a 75% relevant rate.
Above that benchmark, nonzero relevance drops require repeated valid windows
and enough classified ads for the baseline comparison. Production baseline and
observation windows should use the same duration (15 minutes by default),
because unique-ad yield naturally changes with run length.
Baselines also carry a collector metric version. A reference recorded before a
change that adds per-ad work is kept for audit but is not compared against the
new throughput series; the profile learns a new reference from complete runs.

Calibration is blocked on geo mismatch, infrastructure collector errors,
too-short throughput windows, too few scrolls for a zero-ads decision,
cooldown, daily calibration limit, or not enough saved calibration targets.
`resolve_timeout` and `video_timeout` do not discard a relevance observation
when at least 10 ads were already classified; those outcomes occur after the
feed sample has been collected and remain valid account-quality evidence.

Automatic calibration accepts only records explicitly marked relevant that
contain a saved Facebook permalink, a usable full offer URL, or both. Fresh
unclassified ads are never used. The profile opens a saved post first when
possible and otherwise uses the direct offer fallback; it does not scan the feed
or collect new ads during calibration. Calibration requires at least two saved
targets. The health reason still controls how much of the available pool is made
available (normal, low-relevance, or recovery), while the offer-funnel default
runs a 15-minute approach and requires three successful target interactions.
When the pool is smaller than the desired recovery depth, targets may repeat
until the deadline, but a lead form is submitted at most once per target in that
process.

Deep passes scale interaction budgets to the number of targets, capped at 30%
reaction attempts and 10% follow attempts. They require roughly
10% newly confirmed interactions, while a normal pass still requires one.
Legacy passive calibrations still use the dynamic direct-post success ratio.
Offer-funnel calibrations use the bounded 15-minute session and their smaller
success goal because each target now includes prelander/quiz work rather than a
single post view. Expired post links can fall back to a saved relevant offer;
stale cross-domain redirects without offer signals are closed and do not count
as successful calibration work.
Calibration counts as effective after reaching its dynamic view and interaction
goals. An already active like is recorded but
does not satisfy the interaction goal, so the pass continues through the saved
pool looking for a fresh like, follow, or confirmed external CTA visit.

Outside recovery, quality-drop calibrations use a one-hour cooldown so a
single noisy window cannot cause repeated actions. Once a recovery calibration
starts, that profile instead runs up to three immediate validation cycles; the
normal cooldowns are suspended only inside that bounded series. Three failed
validation cycles cause the normal 45-minute profile rest, after which recovery
may start again. Healthy validation ends recovery immediately. Failed
infrastructure attempts use a five-minute retry and do not consume the series.
All calibration attempts still count toward the rolling 36-attempt, 24-hour
safety limit in production. Healthy profiles receive a maintenance calibration
no more than once per three hours, and maintenance never starts a recovery
series. Repeated calibration passes rotate by the number of targets actually
visited instead of reopening the same first posts. Direct targets are
deduplicated into persistent
per-profile and per-geo pools, so a degraded profile can reuse older saved posts
and a new profile can reuse the pool already learned for its geo.

Interrupted runs, timed-out runs, failed collector starts, and short diagnostic
runs are kept in state for audit, but they are not eligible baseline samples and
do not count as repeated zero/low-ad windows.

Calibration can like a directly opened saved post, follow its advertiser, and
visit that post's external CTA without leaving the Octo browser context.
Defaults are bounded:
65% reaction probability, 20% follow probability, at most 6 reaction attempts
and 2 follow attempts per calibration. The first eligible reaction is forced until the
minimum interaction goal is reached. Existing likes/follows are detected and
are never toggled off. Every candidate, classifier decision, attempted action,
and result is written to `engagement_results.json` and `events.jsonl`.

Comments are temporarily disabled in production
(`FACEBOOK_CALIBRATION_COMMENT_EVERY=0`,
`FACEBOOK_CALIBRATION_MAX_COMMENTS=0`). Shares are never performed. Form
submission is disabled by default and is possible only in explicit
`allowlisted` mode with an authorized domain and private test identity. Use
`--interaction-dry-run` on the standalone calibrator to validate matching and
classification without clicking controls.
The comment is counted only after Facebook clears the composer, the exact text
appears in the comments DOM, and the localized posting indicator disappears.
