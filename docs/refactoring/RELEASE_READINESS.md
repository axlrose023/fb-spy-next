# FB Spy refactor: release readiness

Candidate: `b3420a443ddae567a9a9e12137f7616153a0d051`

Status: `LOCAL_LIVE_PASS / PRODUCTION_HOLD`

Local architecture cutover and authorized local Octo validation are complete.
The production server, production database, deployed orchestrator and production
state were not changed.

## Final automated gates

- full Python regression: `888 passed`;
- `ruff check src`: passed;
- `mypy src/app src/cli`: passed for 438 source files;
- architecture, file-size, import-boundary, OpenAPI, CLI and settings contracts:
  passed;
- focused collection, calibration, enrichment and orchestration regression:
  passed;
- frontend TypeScript and Vite production build: passed;
- clean PostgreSQL 18 database upgraded through the complete Alembic chain to
  `d7b1f4a9c632 (head)`;
- `alembic check`: `No new upgrade operations detected`;
- wheel built, installed into a separate Python 3.13 environment and passed the
  `collect`, `calibrate` and `orchestrate` CLI smoke checks;
- wheel contains canonical packages and does not contain `app.services` or
  `app.api.modules`;
- `gitleaks` scanned 98 commits and found no leaks;
- no credentials, Octo token, Gemini key or storage endpoint were added to the
  repository.

## Local application validation

- backend started against a temporary migrated PostgreSQL database;
- authentication, unauthorized rejection, ad import, geo/language filters,
  statistics and ad detail endpoints passed;
- backend media delivery returned `200` for an image and `206` for a ranged
  video request;
- API responses exposed neither storage credentials nor raw S3/Bunny paths;
- desktop `1440x1000` and mobile `390x844` UI checks passed for login, library,
  ad card and detail view without horizontal overflow;
- frontend still uses backend media URLs only.

## Live Octo validation

- Octo Public API discovery found 12 profiles and added them idempotently to an
  isolated catalog; discovered profiles remain without trusted geo until their
  first local proxy connection;
- Spain and Canada started concurrently with separate CDP endpoints and proxy
  countries;
- one 60-second parallel collection produced 4 Spain ads and 1 Canada ad;
- both runs started at the same timestamp, wrote independent UUID-scoped state,
  finished by `time_budget` and had zero duplicate Facebook IDs;
- interest-safe collection recorded zero CTA clicks, video-play attempts and
  comment opens, with `resolved_landings=0` before relevance classification;
- continuous mode with `max_parallel=2` completed exactly two reserved cycles,
  did not start a third cycle and stopped both Octo profiles;
- local run directories use mode `0700`; collection, relevance, enrichment,
  calibration, state and debug JSON/log artifacts use mode `0600`;
- no Octo profile or collector/orchestrator child process remained active after
  validation.

## Defects found and fixed

1. A stale saved Facebook post could match by unique advertiser after the post
   had been reused for another offer. The live case opened an unrelated Amazon
   CTA and was incorrectly counted as a successful calibration target.
2. Saved post matching now requires saved creative metadata when that evidence
   exists. A mismatched CTA domain always fails closed and uses only the saved
   direct offer fallback.
3. The same live target now rejects the unrelated Facebook post, opens only the
   saved `moderninsightreport.com` fallback and remains unsuccessful when no
   current offer/form signal exists.
4. Concurrent Octo profile stops are serialized and rechecked after transport
   errors, preventing teardown races across parallel profiles.
5. Continuous scheduler capacity now reserves running cycles against
   `max_cycles`, preventing an extra cycle during concurrent completion.
6. Collection and orchestration artifacts with full tracking URLs are no longer
   created world-readable.
7. Remaining static typing failures and stale wheel namespace artifacts were
   removed without changing business behavior.

## External blockers

- The configured local Gemini API key is empty. A live classifier invocation
  fails closed with exit code 2 and does not run enrichment or backend import.
  Unit/integration classifier tests pass, but real
  `collect -> classify -> relevant enrichment -> import` validation requires a
  working key.
- Saved calibration pools contain stale posts/offers. The code now rejects or
  quarantines them safely, but a meaningful successful calibration smoke needs
  a fresh confirmed-relevant post and live expected landing.
- Production deployment and production Octo/state validation require separate
  authorization.
- `npm audit --omit=dev` currently reports two moderate React Router findings
  with an available upgrade. The UI does not use SSR hydration, but dependency
  remediation should be handled before the production cutover.

## Production cutover order

1. Provide a working Gemini key and validate one isolated classified run.
2. Confirm active enrichment opens landing/media only for classified relevant
   ads and imports only the resulting relevant artifact.
3. Validate one fresh relevant calibration target with configured interactions
   and submission policy.
4. Back up production database and orchestration state.
5. Deploy the exact candidate using `uv sync --frozen` and the existing secret
   store; do not copy local `.env` files.
6. Run API/auth/media smoke checks and online `alembic current` plus
   `alembic check`.
7. Start two profiles, then increase `max_parallel` only after confirming CPU,
   RAM, Octo teardown, profile locks and rest schedules.
8. Compare relevance, deduplication, media and calibration metrics with the
   pre-cutover baseline before enabling all profiles.

## Rollback

- stop the candidate orchestrator without scheduling new profile cycles;
- restore the previous deployed commit and orchestration state backup;
- no database rollback is required for this refactor candidate because it adds
  no migration;
- retain failed run/state artifacts for diagnosis before another rollout.
