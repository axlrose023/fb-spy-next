# FB Spy refactor: release readiness

Candidate: `54bd2312ec7f087aaaf8f91b0336eaabf0ba760f`

Status: `LOCAL_PASS / PRODUCTION_HOLD`

Локальный архитектурный cutover завершён. Production deployment, server
configuration, live Octo profiles и production state не изменялись. Production
остаётся на hold до отдельно разрешённых live smoke checks.

## Пройденные проверки

- clean detached worktree создан из опубликованного GitHub commit;
- `uv sync --frozen --all-extras` проходит без изменения lockfile;
- полный clean-environment regression: `883 passed`;
- architecture, OpenAPI, CLI, database metadata и settings contracts проходят;
- focused collection/calibration/orchestration/interest-safety regression:
  `252 passed` на fake process, profile, state и browser boundaries;
- wheel собирается, устанавливается в отдельный venv и запускает публичные
  `facebook-spy collect`, `orchestrate` и `calibrate` gateways;
- canonical packages импортируются из wheel, `app.services` и
  `app.api.modules` отсутствуют;
- чистая PostgreSQL 18 база обновляется всей Alembic chain до
  `d7b1f4a9c632 (head)`;
- `alembic check` после upgrade сообщает `No new upgrade operations detected`;
- clean `npm ci` и frontend production build проходят;
- `gitleaks` не находит секретов;
- local `main` и `github/main` совпадают; author/committer новых этапов:
  `axlrose023 <sloboda282@gmail.com>`.

## Исправленный блокер

Migration `c8e7319a42fd` создавала partial unique index
`facebook_ads_geo_fb_ad_id_uidx`, но SQLAlchemy metadata его не описывала.
Из-за drift `alembic check` предлагал удалить production index.

Index зарегистрирован в owning ads persistence adapter с теми же lower-country,
Facebook ID, uniqueness и non-empty predicates. Новая migration не нужна:
существующая schema уже содержит index. Exact PostgreSQL/SQLite metadata
зафиксирована contract test.

## Известные ограничения

- Historical `user_roles` migration выполняет data query через online bind.
  Полная chain не поддерживает `alembic upgrade --sql`; migration validation и
  deployment должны выполняться online на backup/copy database.
- Frontend `npm audit` сохраняет baseline: 6 findings, из них 3 moderate и
  3 high. Новых findings и frontend source/lock changes в рефакторинге нет.
- Wheel smoke дополнительно прошёл с последними версиями в разрешённых ranges,
  но production install должен использовать `uv.lock` и `uv sync --frozen`.
- Live Facebook/Octo collection и calibration намеренно не запускались: это
  запрещено границами текущего локального этапа и создаёт внешние side effects.

## Live validation

Перед production cutover требуется отдельное разрешение и следующий порядок:

1. Зафиксировать deployed commit, backup database и orchestration state.
2. Выполнить online `alembic current` и `alembic check` на копии production DB.
3. Развернуть candidate с прежними env names через frozen lockfile.
4. Проверить API health, auth, ads, runs, stats и protected media delivery.
5. На одном выделенном Octo profile выполнить короткий passive collection.
6. Подтвердить отсутствие CTA/post/landing interactions до relevance decision.
7. Подтвердить enrichment и media persistence только для relevant ads.
8. На сохранённом relevant pool выполнить один ограниченный calibration cycle.
9. Подтвердить post view, configured engagement и landing/offer flow в том же
   Octo context; comments должны следовать текущей disabled/configured policy.
10. Запустить orchestrator с двумя test profiles и `max_parallel=2`.
11. Проверить independent locks, rest schedules, recovery/calibration state,
    discovery нового profile и отсутствие overlap collection/calibration.
12. Сравнить run metrics, relevant ratio, artifacts, deduplication и media URLs
    с pre-cutover baseline, затем только отдельно увеличивать parallelism.

## Rollback

- остановить новый orchestrator без запуска новых profile cycles;
- вернуть предыдущий image/commit;
- восстановить orchestration state backup;
- database rollback не требуется для этого package-only refactor и metadata
  correction, поскольку новая migration не добавлялась;
- при live validation failure сохранить run/state artifacts для анализа до
  повторного запуска.
