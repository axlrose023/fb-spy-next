# FB Spy: пошаговый план модульного рефакторинга

Статус: `IN_PROGRESS` — этап 2 завершен

Этот документ является рабочим контрактом рефакторинга. После начала работ
статус каждого этапа обновляется здесь же. Одновременно выполняется только один
этап. Новый этап не начинается, пока предыдущий не прошел все свои проверки.

## 1. Цель

Перевести текущий backend в модульный монолит с понятной feature-first
структурой, соблюдая:

- SOLID;
- onion architecture и dependency inversion;
- DRY на уровне всего проекта;
- KISS внутри каждого отдельного сценария;
- неизменность текущего пользовательского и production-поведения;
- небольшие файлы и ограниченную сложность;
- возможность откатить каждый этап независимо.

Рефакторинг не должен одновременно менять бизнес-логику. Если во время
переноса обнаруживается баг, сначала добавляется тест, воспроизводящий текущее
поведение. Исправление бага выполняется отдельным изменением после переноса
модуля либо отдельным явно обозначенным коммитом.

### 1.1. Границы рабочей среды

Единственное место, в котором выполняется рефакторинг:

- локальный репозиторий `fb-spy-public-snapshot`;
- GitHub-репозиторий `axlrose023/fb-spy-next`.

Старый репозиторий `fb-spy` остается неизменяемым эталоном. Его разрешено
читать для анализа поведения, зависимостей и сравнения результатов, но в нем
запрещены редактирование, коммиты и push.

До отдельного решения о production cutover запрещены любые действия на сервере:

- deploy, `git pull` и копирование файлов;
- изменение env, secrets, systemd, Docker или reverse proxy;
- restart/stop/start сервисов, orchestrator, Octo или профилей;
- migrations и изменение production database/state;
- production smoke-тесты, создающие side effects.

После каждого полностью завершенного этапа создается отдельный содержательный
коммит и выполняется push только в `fb-spy-next`. Author и committer каждого
коммита: `axlrose023`; trailers `Co-authored-by` не добавляются. Незавершенный
или не прошедший quality gates этап не публикуется как завершенный.

## 2. Исходная точка

Baseline публичного snapshot: `c6b179b`.

Baseline приватной production-версии: `b1e7dce`.

Текущее состояние:

- 21 541 строка Python в `src/app`;
- 317 pytest-тестов;
- `ruff check src` проходит;
- mypy настроен, но еще не добавлен в dev dependencies;
- frontend имеет обязательную проверку `npm run build`;
- production entrypoints используют FastAPI, Taskiq, CLI и отдельные subprocess;
- браузерный runtime зависит от Octo Browser и Playwright;
- объявления и запуски хранятся через SQLAlchemy/PostgreSQL;
- media поддерживает local storage и защищенный S3 backend.

Основные зоны риска:

| Текущий файл | LOC | Основные смешанные ответственности |
|---|---:|---|
| `facebook_runner.py` | 3025 | Octo, Playwright, feed, parsing, screenshots, video, landing, CLI |
| `facebook_orchestrator.py` | 2893 | discovery, scheduling, health, subprocess, state, calibration |
| `facebook/health.py` | 1535 | metrics, baseline, statistics, calibration decision |
| `facebook_calibrator.py` | 1207 | CLI, target loop, navigation, engagement, funnel |
| `facebook/offer_funnel.py` | 1186 | policy, browser navigation, quiz, forms, submit, redaction |
| `facebook/relevance.py` | 1147 | prompt, parsing, rules, guards, classifier orchestration |
| `facebook/engagement.py` | 1068 | policy, selectors, Playwright actions, diagnostics |

## 3. Что не входит в рефакторинг

Пока явно не согласовано обратное, не выполняются:

- изменение UI или API response shapes;
- изменение таблиц, колонок или существующих данных;
- изменение relevance prompt и критериев релевантности;
- изменение calibration thresholds и scheduling policy;
- изменение формата JSON-артефактов и имен файлов;
- изменение CLI-флагов и команд запуска на сервере;
- замена FastAPI, Dishka, Taskiq, SQLAlchemy, Playwright или boto3;
- оптимизация производительности, не требуемая для разделения модулей;
- одновременный rewrite frontend и backend.

## 4. Целевая структура

```text
src/app/
  application.py
  settings.py
  ioc.py
  api.py
  worker.py
  log_config.py

  database/
    base.py
    session.py
    migrations/

  accounts/
    auth/
    users/

  ad_library/
    ads/
    media/
    statistics/

  facebook/
    models.py
    profiles/
    runs/
    collection/
    relevance/
    enrichment/
    calibration/
    orchestration/

    adapters/
      octo/
      playwright/

    commands.py
    tasks.py
```

`accounts`, `ad_library` и `facebook` являются приложениями или bounded
contexts. Внутри них находятся бизнес-модули. Внутри бизнес-модуля находятся
функциональные подмодули.

Новые пустые каталоги заранее не создаются. Каждый пакет появляется только в
том PR, в котором в него переносится реальная ответственность.

## 5. Onion architecture

Луковая архитектура определяется импортами, а не названиями директорий.

Направление зависимостей:

```text
domain models / policies
          ^
        contracts
          ^
 application service / functional services
          ^
 adapters / router / tasks / commands
          ^
        ioc.py
```

### 5.1. Внутреннее ядро

К ядру относятся:

- `models.py`;
- `policies.py`;
- чистые parser/normalization/deduplication функции;
- state machine и decision rules;
- module-specific exceptions.

Ядро не импортирует:

- FastAPI и Pydantic HTTP schemas;
- SQLAlchemy;
- Playwright;
- boto3;
- Google/Gemini SDK;
- httpx;
- subprocess;
- filesystem persistence;
- конкретные реализации соседних модулей.

### 5.2. Контракты

`contracts.py` содержит небольшие consumer-owned `Protocol`.

Примеры отдельных контрактов:

- `FeedReader`;
- `CandidateClassifier`;
- `RelevantAdEnricher`;
- `AdWriter`;
- `ProfileRegistry`;
- `ProfileSession`;
- `RunHistory`;
- `CalibrationExecutor`;
- `StateStore`;
- `ProcessRunner`.

Не создается один большой `BrowserGateway` или `FacebookGateway`. Интерфейс
содержит только методы, необходимые конкретному потребителю.

### 5.3. Application service

Корневой `service.py` является публичным координатором модуля. Он:

- принимает зависимости через конструктор;
- зависит от `Protocol`, а не от SDK;
- координирует один бизнес-сценарий;
- не содержит Playwright selectors, SQL queries или S3 key construction;
- не повторяет внутреннюю реализацию функциональных подмодулей.

### 5.4. Адаптеры

Конкретные технологии реализуют контракты во внешнем кольце:

```text
relevance/adapters/gemini.py
media/adapters/s3.py
media/adapters/local.py
ads/adapters/persistence/repository.py
facebook/adapters/octo/client.py
facebook/adapters/playwright/feed_reader.py
calibration/adapters/playwright/engagement.py
orchestration/adapters/subprocess_runner.py
```

Адаптер может импортировать модели и контракты внутреннего слоя. Обратный
импорт запрещен.

### 5.5. Delivery layer

К delivery относятся:

- `router.py`;
- `schemas.py`;
- `tasks.py`;
- `commands.py`.

Они валидируют вход, вызывают публичный service и преобразуют результат. В них
не размещается бизнес-логика.

## 6. Стандарт бизнес-модуля

```text
<module>/
  __init__.py
  service.py
  models.py
  contracts.py
  exceptions.py

  policies.py             # только при наличии чистых правил

  <capability>/           # функциональный подмодуль

  adapters/               # реализации внешних контрактов
    <technology>/

  router.py               # только при наличии HTTP API
  schemas.py              # только при наличии HTTP API
  tasks.py                # только при наличии Taskiq entrypoint
  commands.py             # только при наличии CLI
```

Обязательны только `__init__.py` и `service.py`. Остальные файлы создаются,
если соответствующая ответственность существует.

### 6.1. Три типа пакетов

1. Бизнес-модуль имеет публичный `service.py`.
2. Функциональный подмодуль именуется по выполняемой функции и не обязан иметь
   искусственный service.
3. Adapter package именуется по технологии или внешней границе и реализует
   контракт.

Например, `candidates/normalization.py` не получает пустой `service.py`, но
`feed/service.py` получает его, если feed scan является самостоятельным use
case.

### 6.2. Публичный API

`__init__.py` экспортирует только стабильный внешний API модуля:

```python
from .models import CollectionRequest, CollectionResult
from .service import CollectionService
```

Другие модули не импортируют внутренние файлы вида
`collection.feed.navigator`. Они используют публичный API либо собственный
consumer-owned Protocol.

## 7. Ограничения размера и сложности

Для production-кода действуют следующие ориентиры:

- обычный Python-файл: целевой размер до 250 строк;
- adapter с линейной integration-логикой: до 300 строк;
- файл свыше 350 строк блокирует merge, пока не разделен либо не описано
  конкретное исключение;
- `service.py`: целевой размер 100–250 строк;
- функция или метод: обычно до 50 строк;
- orchestration-функция может быть длиннее только при сохранении линейного
  сценария и отсутствии вложенной бизнес-логики;
- цикломатическая сложность новых функций не должна скрываться через общий
  `# noqa: C901`;
- generated files и Alembic migrations исключаются из size gate;
- тестовый файл свыше 450 строк разделяется по поведению или сценарию.

Число строк является сигналом, а не единственным критерием. Файл разделяется
раньше, если в нем появились две независимые причины для изменения.

## 8. DRY и KISS

### 8.1. Куда переносить повторяющуюся логику

- повтор внутри одного функционального подмодуля остается в нем;
- повтор между подмодулями одного business module поднимается в корень этого
  модуля;
- повтор между Facebook-модулями переносится в конкретно названный пакет внутри
  `facebook`, например `facebook/adapters/playwright`;
- повтор между приложениями выносится только при доказанной нейтральности и
  получает предметное имя;
- папки `common`, `shared`, `helpers` и общий `utils.py` не создаются.

Используется rule of three: общий abstraction обычно создается после третьего
реального повторения. Исключение — security-critical normalization, signing,
redaction или locking, где два разных варианта уже создают риск.

### 8.2. Что не считается DRY

Не объединяются только потому, что выглядят похоже:

- transport schema и domain model;
- SQLAlchemy model и immutable domain model;
- collection navigation и calibration navigation с разными инвариантами;
- разные policy, случайно имеющие одинаковые условия сейчас.

### 8.3. KISS

- Protocol создается только на реальной границе или в точке вариативности;
- не создаются `BaseService`, `BaseRepository` и abstract factory без нескольких
  реализаций;
- pure function предпочтительнее class без состояния;
- dataclass предпочтительнее словаря с неявными ключами;
- composition предпочтительнее наследования;
- feature flags не используются для постоянного существования old/new версий.

## 9. Неприкосновенные поведенческие инварианты

Рефакторинг обязан сохранять:

1. Каждый Octo-профиль работает независимо.
2. Один профиль не запускает collection и calibration одновременно.
3. Максимальный параллелизм соблюдается глобально.
4. Geo определяется из Octo-профиля и сохраняется в run/ad.
5. До подтверждения relevance не выполняются активные переходы по CTA и
   landing URL в профильном браузере.
6. Нерелевантные объявления не открывают landing и не попадают в ad library.
7. Enrichment принимает только подтвержденный `RelevantAd`.
8. Calibration использует только проверенный relevant target pool.
9. Calibration не импортирует рекламу как новый collection result.
10. Комментарии остаются отключенными, пока настройка явно не изменена.
11. Offer submit остается выключенным без allowlist и явного режима.
12. S3 credentials и реальные object URLs не возвращаются frontend.
13. Media URL остается backend-signed/backend-proxied.
14. Deduplication не создает вторую запись одной рекламы в одном geo.
15. Текущие CLI-флаги, JSON-файлы и API routes сохраняются до финального
    cutover.

## 10. Целевая цепочка обычного запуска

```text
FeedReader
  -> AdCandidate
  -> RelevanceService
  -> RelevanceDecision
  -> RelevantAd
  -> EnrichmentService
  -> EnrichedAd
  -> AdLibrary writer
```

Cross-stage value objects размещаются в `facebook/models.py`. Этот файл содержит
только небольшие immutable типы, используемые несколькими Facebook-модулями.
Если он приближается к 250 строкам, типы разделяются по lifecycle-стадиям.

Collection service зависит от небольших контрактов classifier/enricher/writer.
Конкретные `RelevanceService`, `EnrichmentService` и ad repository связываются
в `ioc.py`.

## 11. Общая стратегия тестирования

### 11.1. Пирамида

1. Pure unit tests для policies, parsing, normalization и state transitions.
2. Contract tests для всех реализаций Protocol.
3. Integration tests для SQLAlchemy, filesystem, S3 client wrappers и API.
4. Component tests для полного бизнес-модуля с fake adapters.
5. Process/CLI tests для entrypoints и subprocess command construction.
6. Browser fixture tests без реального Facebook.
7. Ограниченные manual smoke tests на выделенном Octo-профиле.

Реальный Facebook, production S3 и реальные offer submit не используются в CI.

### 11.2. Characterization before migration

Перед переносом каждого модуля сначала добавляются тесты на текущую реализацию:

- успешный сценарий;
- пустой результат;
- ошибка внешнего сервиса;
- timeout/cancellation;
- повторный запуск/idempotency;
- поврежденное или частичное состояние;
- security и redaction;
- восстановление после процесса, завершенного посередине.

После этого те же fixtures используются против новой реализации.

### 11.3. Differential testing

Для чистой логики old и new implementation временно запускаются на одинаковом
fixture. Сравниваются:

- decision;
- normalized data;
- dedup keys;
- generated subprocess arguments;
- metrics;
- state transitions;
- serialized JSON без нестабильных timestamp/paths.

Old и new реализации никогда не запускаются параллельно против одного реального
Facebook-профиля, потому что это создало бы двойные side effects.

### 11.4. Детерминированность

Clock, random, process runner и browser boundary передаются через небольшие
контракты там, где они влияют на решение. Тесты не используют настоящий sleep.

Проверяются:

- точные deadline;
- cooldown;
- burst cycles;
- retry/backoff;
- cancellation;
- restart после сохраненного state;
- параллельные профили при фиксированном capacity.

### 11.5. Database

При простом переносе файлов database migration не создается.

До и после каждого persistence-модуля сравниваются:

- table names;
- columns и types;
- indexes;
- foreign keys;
- unique constraints;
- cascade behavior;
- Alembic head;
- импорт существующей production-like строки.

ORM models находятся во внешнем persistence adapter. Domain models не являются
SQLAlchemy entities.

### 11.6. API

Для каждого HTTP-модуля фиксируются:

- route и HTTP method;
- auth requirements;
- request schema;
- response fields;
- status codes;
- pagination/filter semantics;
- error response;
- OpenAPI contract.

Перенос router считается корректным только при сохранении API-контракта.

### 11.7. Frontend

Если backend API shape не менялся, frontend-код не редактируется. При переносе
ads/media/stats/runs обязательно выполняется:

```bash
cd frontend
npm ci
npm run build
```

Отдельно проверяются media proxy URLs, geo/language filters и detail page.

### 11.8. Browser automation

Автоматические тесты используют:

- сохраненные HTML fixtures;
- fake Page/Context boundary;
- fake Octo API;
- временную файловую систему;
- заранее определенные navigation outcomes.

Manual smoke проводится только после зеленых unit/component tests и включает:

- старт/стоп одного тестового профиля;
- passive feed scan;
- отсутствие открытия нерелевантного landing;
- enrichment одного relevant ad;
- calibration на ограниченном target pool;
- корректное закрытие вкладок и профиля.

### 11.9. Security

Перед каждым публичным push:

- secret scan;
- проверка отсутствия `.env`;
- проверка отсутствия реальных profile UUID/IP/credentials;
- тесты path traversal и signed media URLs;
- проверка redaction URL/query/form data в логах.

## 12. Quality gates каждого PR

Минимальные команды:

```bash
uv run ruff check src
uv run pytest -q <tests текущего модуля>
uv run pytest -q
```

После добавления mypy:

```bash
uv run mypy src/app/<измененный пакет>
```

Если затронут frontend/API contract:

```bash
cd frontend
npm ci
npm run build
```

Merge запрещен, если:

- упал хотя бы один baseline test;
- изменился API/CLI/JSON contract без отдельного согласования;
- новый inner module импортирует concrete adapter;
- старый и новый файлы содержат две копии одной бизнес-логики;
- появился production-файл больше установленного size gate;
- compatibility wrapper содержит новую логику;
- не описан rollback текущего этапа.

### 12.1. Дополнительный архитектурный аудит

План является исходной картой, но не заменяет повторный анализ реального кода.
Перед изменением каждого модуля дополнительно проверяются:

- фактический import/dependency graph и скрытые consumers;
- cohesion модуля и корректность выбранной границы ответственности;
- coupling с соседними модулями, entrypoints и persistence;
- дубли бизнес-правил, selectors, parsers, serializers и конфигурации;
- dead code, неиспользуемые flags, wrappers и устаревшие entrypoints;
- нарушение SOLID, onion dependency direction, DRY и KISS;
- testability, детерминированность и управляемость side effects;
- безопасность secrets, URL, media, logs и внешних adapters;
- потенциально лишние DB queries, browser actions, subprocess и filesystem I/O;
- timeout, retry, cancellation, resource cleanup и параллельный доступ.

После переноса аудит повторяется по итоговому diff. Проверяется, что перенос:

- не создал новую универсальную абстракцию без реального второго потребителя;
- не оставил две рабочие реализации одной бизнес-логики;
- не увеличил связанность и количество циклических импортов;
- не добавил лишние browser/network/database операции;
- не ухудшил наблюдаемость, обработку ошибок или безопасность;
- не оставил временный код без срока и условия удаления.

Результаты аудита распределяются строго:

1. Необходимое для безопасного переноса исправляется в текущем этапе и
   покрывается тестом.
2. Баг текущего поведения фиксируется characterization-тестом, но исправляется
   отдельным согласованным коммитом.
3. Изменение business policy или поведения только записывается в backlog.
4. Оптимизация выполняется только при измеримом эффекте или устранении явно
   лишней операции; speculative optimization в рефакторинг не включается.

Если аудит меняет границы или порядок этапа, сначала обновляется этот документ,
и только затем начинается реализация.

### 12.2. Правило фиксации этапа

Завершение каждого этапа оформляется одним понятным итоговым коммитом либо
небольшой последовательностью атомарных коммитов, если этап имеет независимые
подэтапы. Во всех случаях:

- commit message описывает перенесенную ответственность, а не факт правки;
- в commit не попадают media, archives, local state, credentials и unrelated files;
- author и committer остаются `axlrose023`;
- после последнего quality gate выполняется push только в `fb-spy-next`;
- старый GitHub-репозиторий и production server не используются как target.

## 13. Универсальный playbook переноса одного модуля

Каждый модуль проходит одинаковые шаги.

### Шаг A. Inventory

- перечислить старые файлы и публичные symbols;
- найти все imports и entrypoints;
- перечислить side effects;
- определить владельца данных;
- зафиксировать входы, выходы и ошибки;
- найти дубли и dead code;
- записать текущие размеры файлов.

### Шаг B. Characterization tests

- дополнить тесты текущей реализации;
- создать reusable fixtures;
- зафиксировать serialized output;
- зафиксировать timeout/error behavior;
- запустить весь baseline suite.

### Шаг C. Public contract

- определить module models;
- определить consumer-owned Protocol;
- определить module exceptions;
- определить единственный публичный service;
- описать разрешенные зависимости.

### Шаг D. Pure core

- сначала перенести pure models/rules/policies;
- выполнить differential tests old/new;
- удалить старую копию pure logic;
- оставить re-export только при необходимости совместимости.

### Шаг E. Adapters

- реализовать каждый внешний контракт отдельно;
- добавить contract tests;
- преобразовать SDK exceptions в module exceptions;
- проверить timeout, cancellation и redaction.

### Шаг F. Application service

- собрать сценарий через dependency injection;
- не переносить CLI/API parsing внутрь service;
- проверить happy path и partial failure;
- проверить idempotency и cleanup.

### Шаг G. Compatibility switch

- старый import path становится тонким wrapper/re-export;
- entrypoint продолжает принимать старые аргументы;
- `ioc.py` переключается на новый service;
- выполняется полный suite;
- выполняется component smoke.

### Шаг H. Cleanup

- обновить все внутренние imports;
- удалить compatibility wrapper после отсутствия consumers;
- удалить dead code и повторяющиеся helpers;
- обновить этот документ;
- зафиксировать rollback commit.

Один PR не должен одновременно проходить этот playbook для двух независимых
business modules.

## 14. Пошаговая последовательность

### Этап 0. Guardrails и инструменты

Статус: `COMPLETED` — 2026-08-07

Изменения:

- добавить mypy в dev dependencies;
- добавить import-linter или эквивалентные architecture tests;
- добавить CI workflow после выдачи OAuth `workflow` scope;
- разделить pytest markers: unit, contract, integration, browser, smoke;
- зафиксировать API routes/OpenAPI baseline;
- зафиксировать CLI `--help` baseline;
- зафиксировать database metadata baseline;
- добавить file-size/forbidden-import check для новых пакетов;
- записать текущий coverage baseline без искусственного повышения порога.

Проверки:

- 317 baseline tests проходят;
- ruff проходит;
- frontend build проходит;
- architecture checks не применяются к legacy paths, но обязательны для новых;
- никакое production-поведение не изменено.

Rollback: удаление только tooling/config commit.

Результат:

- `mypy 1.20.2` закреплен в dev dependencies и `uv.lock`;
- pre-commit версии Ruff/mypy синхронизированы с локальным toolchain;
- strict pytest markers зарегистрированы, а будущие module tests обязаны явно
  указывать свой test kind;
- AST architecture checks контролируют новые `accounts`, `ad_library` и
  `facebook`, не применяя новые границы к legacy paths;
- inner layers не могут импортировать frameworks, SDK, legacy infrastructure
  или concrete adapters;
- cross-module imports разрешены только через публичный package API;
- generic `common/shared/helpers/services/utils` запрещены в новых модулях;
- новые production-файлы ограничены 250 строками, adapters — 300, tests — 450;
- зафиксированы 15 API paths и полный canonical OpenAPI contract;
- зафиксированы 20 CLI help contracts и SQLAlchemy metadata contract;
- baseline: 317 исходных тестов и branch coverage 59.90%;
- итоговый suite: 351 тест, включая 34 architecture/contract checks;
- `ruff`, strict mypy для новых checks, pre-commit и frontend build проходят;
- GitHub Actions workflow отложен: OAuth token пока не имеет scope `workflow`;
- 5 существующих frontend dependency findings записаны в
  `docs/refactoring/BASELINES.md` и не смешаны с backend refactor.

Production-код и business policy не менялись. Старый репозиторий и server не
использовались. Rollback выполняется revert одного tooling-коммита этапа 0.

### Этап 1. `accounts/auth`

Статус: `COMPLETED` — 2026-08-07

Источники:

```text
api/modules/auth/
api/modules/auth/services/auth.py
api/modules/auth/services/jwt.py
```

Цель:

```text
accounts/auth/
  service.py
  models.py
  contracts.py
  exceptions.py
  router.py
  schemas.py
  dependencies.py
  adapters/
    jwt.py
    passwords.py
    users.py
```

Порядок:

1. Добавить characterization tests login/refresh/invalid token/disabled user.
2. Выделить `TokenCodec`, `PasswordVerifier` и минимальный user reader contract.
3. Перенести JWT и password hashing в adapters.
4. Перенести AuthService без зависимости от UnitOfWork mega-object.
5. Перенести router/schemas с неизменными routes.
6. Оставить временные re-export старых imports.
7. Переключить Dishka provider.
8. Удалить старые файлы после проверки consumers.

Критические тесты:

- access/refresh expiration;
- wrong token type;
- invalid signature;
- password mismatch;
- user not found/disabled;
- API status codes и response shape.

Результат:

- создан публичный модуль `accounts/auth` с чистыми моделями, исключениями,
  consumer-owned Protocol и application service;
- `AuthService` зависит только от `UserReader`, `TokenCodec` и
  `PasswordVerifier`, не импортирует FastAPI, SQLAlchemy, settings или
  `UnitOfWork`;
- JWT, bcrypt и преобразование legacy `User` вынесены в отдельные adapters;
- защищенные routes используют неизменяемый `CurrentUser` без ORM-модели и
  password hash;
- login и refresh переведены на один `AuthService`, а Dishka собирает его в
  composition root из узких зависимостей;
- рабочие imports переведены на публичный `app.accounts.auth`; старые auth paths
  оставлены как migration wrappers и не содержат второй реализации JWT;
- API routes, request/response schemas, status codes, token claims и TTL
  сохранены; OpenAPI contract hash не изменился;
- добавлено 29 unit/integration tests для login, refresh, access dependency,
  expiration, signature, token type, payload и disabled/missing users;
- подписанный access token с невалидным UUID теперь корректно возвращает `401`
  вместо необработанного `ValueError`/`500`; это единственная намеренная
  security-коррекция поведения;
- новый auth core и adapters имеют 100% branch coverage, router покрыт всеми
  публичными ветками, общий branch coverage вырос с 59.90% до 60.80%;
- полный suite, architecture/contract checks, strict mypy, Ruff, pre-commit,
  frontend build и gitleaks проходят.

Database schema, frontend и production runtime не менялись. Старый репозиторий
и server не использовались. Rollback выполняется revert одного коммита этапа 1.

Audit observations, намеренно не смешанные с refactor-only этапом:

- `LegacyUserReader` и compatibility wrappers удаляются после переноса
  `accounts/users`, когда исчезнет зависимость от legacy ORM/gateway;
- refresh tokens остаются повторно используемыми до истечения TTL: rotation,
  revocation и `jti` требуют отдельного изменения auth policy;
- rate limiting login endpoint отсутствует и должен проектироваться вместе с
  доверенной proxy/IP boundary, а не добавляться локально в router;
- уникальность username пока не закреплена database constraint и относится к
  этапу 2, где переносится users persistence.

### Этап 2. `accounts/users`

Статус: `COMPLETED` — 2026-08-07

Источники: `api/modules/users/`.

Цель:

```text
accounts/users/
  service.py
  models.py
  contracts.py
  exceptions.py
  router.py
  schemas.py
  adapters/persistence/
    models.py
    repository.py
```

Проверки:

- CRUD и роли;
- username uniqueness;
- password не возвращается наружу;
- authorization границы admin/user;
- schema и table parity;
- существующие строки читаются после переноса без migration.

Результат:

- создан модуль `accounts/users` с чистыми `User`, `UserAccount`, command/query
  models, module exceptions и consumer-owned contracts;
- `UserService` зависит только от `UserRepository` и `PasswordHasher`, не
  импортирует FastAPI, Pydantic, SQLAlchemy, settings или `UnitOfWork`;
- правила create/update, admin-only полей, self-update и username availability
  перенесены в application service с сохранением порядка проверок;
- SQLAlchemy-модель и repository вынесены в `adapters/persistence`; универсальный
  `build_filters` заменен явными users-фильтрами;
- repository возвращает domain objects, а password hash не входит в публичный
  `User`, API schemas или `CurrentUser`;
- auth читает учетные записи через публичный users contract и новый repository;
  рабочие routes и Dishka больше не зависят от legacy user service/gateway;
- старые `api/modules/users` paths оставлены тонкими migration wrappers; старый
  gateway используется только compatibility `UnitOfWork/JwtService` facade;
- OpenAPI contract и SQLAlchemy metadata hash не изменились, migration не нужна,
  существующая таблица `users` читается прежним форматом;
- добавлено 12 users unit/integration tests: CRUD, pagination/filters, role
  boundaries, self-update, duplicate username, missing/disabled users и
  repository round trip;
- полный suite: 392 теста; users service/repository имеют 100% branch coverage,
  focused module coverage — 95%, общий combined coverage — 61.84%;
- Ruff, strict mypy и architecture/contract checks проходят.

Audit observations, не измененные в refactor-only этапе:

- username availability проверяется application service, но database unique
  constraint отсутствует; конкурентные create требуют отдельной migration;
- любой авторизованный пользователь по текущему API может получать список и
  карточки других пользователей; ужесточение является изменением access policy;
- минимальная длина пароля по прежнему равна одному символу; password policy и
  принудительная смена пароля требуют отдельного security-этапа;
- compatibility `UserGateway`, `UnitOfWork.users` и legacy JWT facade удаляются
  вместе с остальными legacy consumers на этапе 14.

Frontend, server и production runtime не менялись. Старый репозиторий не
использовался. Rollback выполняется revert одного коммита этапа 2.

### Этап 3. `ad_library/media`

Статус: `COMPLETED` — 2026-08-07

Источники:

```text
services/media_storage.py
api/modules/media/
```

Цель:

```text
ad_library/media/
  service.py
  models.py
  contracts.py
  exceptions.py
  router.py
  schemas.py
  signing/
    policy.py
    tokens.py
  paths/
    validation.py
    object_keys.py
  adapters/
    local.py
    s3.py
```

Порядок переноса:

1. Signing и path validation как pure core.
2. Local adapter и contract tests.
3. S3 adapter и fake boto client tests.
4. MediaService.
5. Backend proxy router.
6. IoC switch.
7. Замена `media_storage.py` на тонкий compatibility facade; окончательное
   удаление import path выполняется на этапе 14.

Критические тесты:

- path traversal;
- подпись и expiration;
- привязка object key к ad UUID и media kind;
- отсутствие bucket endpoint в API;
- независимость write/read-only/signing secrets;
- local/S3 contract parity;
- missing object и range/content headers.

Результат:

- signing, path/object-key validation, byte ranges и streaming вынесены в pure
  module code; FastAPI, settings, boto3 и legacy gateway остаются только во
  внешних router/configuration/adapters;
- local filesystem и S3 реализованы раздельными adapters, синхронные boto3 и
  filesystem операции не блокируют event loop, а provider errors переводятся в
  module exceptions;
- `MediaService` проверяет подписанный token до чтения ссылки объявления и
  отдает только backend proxy payload; S3 reference, bucket и endpoint не входят
  в URL или response headers;
- S3 object key привязан к UUID объявления, media kind и разрешенному suffix;
  local paths защищены от parent traversal и symlink escape;
- сохранена обязательная relevance gate перед S3 upload, раздельные write,
  read-only и signing credentials, multipart settings и прежняя object layout;
- API router и Dishka переключены на новый модуль; OpenAPI и SQLAlchemy metadata
  contracts не изменились, frontend-код не менялся;
- legacy `services/media_storage.py` сокращен с 641 до 144 строк и содержит
  только constructor-compatible delegation/re-exports; production consumers
  больше не импортируют этот path;
- добавлено 39 media unit tests, включая token binding/expiry, unsafe paths,
  S3 `404/416/5xx`, GET/HEAD proxy headers, stream cleanup и error mapping;
- focused media branch coverage — 94%, S3 adapter — 92.56%, proxy router —
  97.62%; полный suite — 431 тест, общий branch coverage — 62.82%;
- Ruff, strict mypy, полный pre-commit, architecture/contract checks, frontend
  build и gitleaks проходят;
- pre-commit Python hooks явно закреплены на project runtime Python 3.13;
  isolated mypy return types предыдущего users-модуля сделаны явными без
  изменения runtime behavior.

Audit observations, не измененные в refactor-only этапе:

- batch upload сохраняет legacy partial-failure semantics: если один объект
  падает после успешных upload, уже созданные remote objects автоматически не
  удаляются; transactional cleanup/idempotency требует отдельного изменения;
- `LegacyAdMediaReader` зависит от legacy `FacebookAdGateway` до переноса
  `ad_library/ads` на этапе 4;
- compatibility facade остается только для legacy tests/external import path и
  удаляется на этапе 14 после проверки отсутствия внешних consumers;
- `npm audit` по неизмененному frontend dependency tree по-прежнему сообщает 5
  ранее зафиксированных findings (3 moderate, 2 high); auto-fix с breaking
  dependency updates в media-refactor не выполнялся.

Server, Octo и production runtime не менялись. Старый репозиторий не
использовался. Rollback выполняется revert одного коммита этапа 3.

### Этап 4. `ad_library/ads`

Статус: `COMPLETED` — 2026-08-07

Источники:

```text
api/modules/ads/
services/facebook/importer.py
services/facebook_db_importer.py
```

Цель:

```text
ad_library/ads/
  service.py
  models.py
  contracts.py
  exceptions.py
  router.py
  schemas.py
  catalog/
    queries.py
    filters.py
  ingestion/
    service.py
    mapping.py
    deduplication.py
  adapters/persistence/
    models.py
    repository.py
```

Критические тесты:

- импорт только relevant/enriched ads;
- dedup одного объявления;
- сохранение country/language;
- фильтры geo/language;
- pagination и ordering;
- media references;
- повторный import идемпотентен;
- rollback транзакции при partial media failure.

Результат:

- каталог объявлений, query model, response mapping и persistence перенесены в
  `ad_library/ads`; HTTP router зависит от `AdService`, а application layer —
  только от `AdReader`/`MediaLinkBuilder` contracts;
- SQLAlchemy model и repository находятся во внешнем persistence adapter;
  фильтры geo/language/search, pagination и ordering сохранены, `order_by`
  ограничен явным whitelist и не попадает в SQL как произвольное имя;
- importer делегирует mapping, language normalization, deduplication, media
  upload и запись в БД в `AdIngestionService`; синхронная нормализация путей
  выполняется вне event loop;
- identity объявления сохранена как нормализованная пара `(country, fb_ad_id)`;
  batch dedup и повторный import одного run идемпотентны;
- media загружаются только после relevance gate и до записи строк объявления;
  ошибка upload не оставляет новые ad rows, а транзакционный integration test
  подтверждает rollback run и ads;
- country, language, source identity, timestamps и media paths сохраняют legacy
  mapping; OpenAPI и SQLAlchemy metadata contracts не изменились;
- API формирует только подписанные backend media URLs через `MediaLinkBuilder`;
  raw local/S3 paths, bucket и endpoint не входят в API response;
- старые `api/modules/ads/*` и `services/facebook/language.py` стали тонкими
  compatibility facades; production router, IoC, UoW и media reader переключены
  на новый модуль;
- добавлено 12 ads unit/integration tests; focused coverage модуля — 97%, полный
  suite — 443 теста, общий branch coverage — 63.45%; Ruff, strict mypy, полный
  pre-commit, architecture/contract checks, frontend build и gitleaks проходят.

Audit observations, не измененные в refactor-only этапе:

- dedup защищает последовательные и batch imports, но database unique constraint
  для `(country, fb_ad_id)` отсутствует; два конкурентных transaction всё ещё
  могут создать одинаковые строки, поэтому constraint требует отдельной
  миграции и согласованной политики обработки конфликтов;
- при partial S3 batch failure транзакция БД откатывается, но уже загруженные до
  ошибки remote objects не удаляются автоматически; compensation относится к
  отдельному transactional media изменению;
- streaming relevance coordination и run lifecycle пока остаются в legacy
  importer и будут вынесены на этапах `facebook/relevance` и `facebook/runs`;
- `npm audit` по неизмененному frontend dependency tree сообщает те же 5 findings
  (3 moderate, 2 high); обновление Vite/React Router не смешивалось с backend
  refactor.

Server, Octo и production runtime не менялись. Старый репозиторий не
использовался. Rollback выполняется revert одного коммита этапа 4.

### Этап 5. `ad_library/statistics`

Статус: `COMPLETED` — 2026-08-07

Источники: `api/modules/stats/`.

Цель:

```text
ad_library/statistics/
  service.py
  models.py
  contracts.py
  router.py
  schemas.py
  adapters/persistence.py
```

Проверки:

- total/facet counts совпадают с legacy;
- country/language/domain null handling;
- пустая база;
- API schema не меняется;
- queries не зависят от HTTP schemas.

Результат:

- immutable `AdStatistics`/`Facet`, reader contract и application service
  вынесены в `ad_library/statistics`; inner layer не импортирует FastAPI,
  Pydantic, SQLAlchemy, UoW или соседние adapters;
- SQLAlchemy reader подключается в composition root с read model таблицы ads,
  поэтому statistics не зависит от внутреннего persistence path модуля ads и
  ORM-модель не выставляется в его публичный domain API;
- пять summary counts объединены в один conditional aggregate query, десять
  facets — в один ограниченный `UNION ALL` query; `/stats/ads` выполняет два
  `SELECT` вместо пятнадцати, что закреплено integration test;
- сохранены legacy semantics для link/resolved/video/bad-screenshot counts,
  facet limit 30, descending count order и исключение `NULL`/пустых значений;
- router возвращает прежнюю Pydantic schema через явный domain-to-response
  mapper; authentication, route и точный OpenAPI digest не изменились;
- старые `api/modules/stats/*` стали тонкими compatibility facades, production
  router и Dishka provider используют новый модуль;
- добавлено 4 unit/integration tests; focused branch coverage модуля — 100%,
  полный suite — 447 тестов, общий branch coverage — 63.66%; strict mypy, Ruff,
  полный pre-commit, architecture/OpenAPI/database contracts, frontend build и
  gitleaks проходят.

Audit observations, не измененные в refactor-only этапе:

- статистика остаётся глобальным live snapshot по всей таблице без geo/time
  scope, как и существующий API contract;
- два SQL-запроса устраняют лишние round trips, но high-cardinality facets
  `domain`/`advertiser` всё равно выполняют полный aggregate scan; cache,
  materialized view или отдельные counters следует добавлять только после
  production measurements и определения допустимой freshness;
- порядок facet values с одинаковым count остаётся неопределённым, как в legacy
  query; добавление tie-breaker было бы отдельным изменением API behavior;
- frontend dependency tree не менялся и сохраняет ранее зафиксированные 5 npm
  audit findings (3 moderate, 2 high).

Server, Octo и production runtime не менялись. Старый репозиторий не
использовался. Rollback выполняется revert одного коммита этапа 5.

### Этап 6. `facebook/runs`

Статус: `COMPLETED` — 2026-08-09

Источники:

```text
api/modules/runs/
services/facebook/runner_process.py
services/facebook_db_importer.py
часть services/facebook/health.py
```

Цель:

```text
facebook/runs/
  service.py
  models.py
  contracts.py
  exceptions.py
  router.py
  schemas.py
  metrics/
    models.py
    collector.py
    normalization.py
  adapters/
    persistence/
      models.py
      repository.py
    process_runner.py
```

На этом этапе из `health.py` переносятся только факты RunMetrics и их сбор.
Calibration decisions остаются до своего этапа.

Проверки:

- create/start/finish/fail lifecycle;
- process PID/return code;
- import run result;
- metrics parity на существующих JSON fixtures;
- process cancellation и timeout;
- таблица и relationship с ads не меняются.

Результат:

- immutable domain models, application `RunService` и узкие contracts для
  repository, transaction, process runner, importer и artifact staging вынесены
  в `facebook/runs`; inner layer не импортирует FastAPI, Pydantic, SQLAlchemy,
  UoW, subprocess или settings;
- lifecycle start/import/stop сохраняет прежние transaction boundaries и HTTP
  semantics: run фиксируется до старта процесса, импорт выполняется в одной DB
  transaction, остановка требует активного процесса и переводит run в
  `stopping`;
- SQLAlchemy model, mapping, repository и transaction adapter перенесены во
  внешний persistence package; имя таблицы, колонки, индексы, relationship и
  OpenAPI contract не изменились;
- process registry физически перенесён в `adapters/processes`; spawn в отдельной
  process group, PID/runtime paths, terminal status, streaming import drain и
  SIGTERM semantics сохранены, старый import path стал compatibility facade;
- `RunMetrics` и весь сбор фактов вынесены из legacy `health.py` в отдельный
  `metrics` package; calibration policy и решения намеренно остаются в
  `health.py` до этапа orchestration/calibration;
- API router подключён напрямую к новому модулю через composition root, а
  прежние `api/modules/runs/*` оставлены тонкими compatibility facades для
  переходных consumers;
- operational DB-import command перенесён в `facebook/runs/commands.py`, при
  этом прежний module entrypoint и точный `--help` contract сохранены для
  orchestrator;
- добавлено 15 unit/integration/characterization tests для defaults и явного
  `resolve_max=0`, filters/errors, staging/import, PID/return code/SIGTERM,
  process flags, idempotent completed-run import и повреждённых metric inputs;
  focused branch coverage модуля — 90%, полный suite — 472 теста, общий combined
  coverage — 66.29%; strict mypy, Ruff, architecture/OpenAPI/database/CLI
  contracts проходят.

Audit observations, не измененные в refactor-only этапе:

- registry хранит process handles только в памяти; после рестарта API процесс
  может продолжить работу по сохранённому PID, но текущий stop endpoint уже не
  сможет им управлять. Durable process recovery относится к будущему lifecycle
  orchestration, где необходимо валидировать PID ownership, а не слепо посылать
  signal;
- если subprocess spawn завершится ошибкой после commit, в БД останется run со
  статусом `created`, как и до переноса; отдельная compensating transition в
  `failed` будет behavior change и должна внедряться вместе с recovery policy;
- staging внешней директории выполняется до DB transaction и использует basename
  исходного run; collision или ошибка последующего import могут оставить
  скопированные artifacts. Idempotent UUID destination и cleanup compensation
  следует добавлять отдельным storage/lifecycle изменением;
- process monitor и importer пока используют legacy UoW/ORM bridge, потому что
  streaming relevance pipeline переносится на следующих этапах; dependency не
  протекает в domain/application contracts;
- допустимые status strings по-прежнему не закреплены database constraint или
  domain state machine. Их формализация выполняется вместе с lifecycle module,
  чтобы не изменить существующие operational состояния частичным решением.
- frontend source и dependency lock не менялись; актуальный `npm audit` теперь
  сообщает 6 findings (3 moderate, 3 high) вместо ранее зафиксированных 5 из-за
  обновившейся advisory database. Их устранение требует отдельного dependency
  upgrade и не смешивается с backend refactor.

Server, Octo и production runtime не менялись. Старый репозиторий не
использовался. Rollback выполняется revert одного коммита этапа 6.

### Этап 7. `facebook/profiles` и Octo boundary

Статус: `COMPLETED` — 2026-08-09

Источники:

- Octo функции из runner/orchestrator;
- profile discovery из orchestrator;
- geo normalization;
- baseline-related часть `health.py`.

Цель:

```text
facebook/profiles/
  service.py
  models.py
  contracts.py
  exceptions.py
  discovery/
    service.py
    mapping.py
    geo.py
  baseline/
    models.py
    builder.py
    validation.py

facebook/adapters/octo/
  client.py
  profiles.py
  sessions.py
  mapping.py
```

Проверки:

- public API discovery;
- local API start/stop;
- новые профили подхватываются один раз;
- geo извлекается и нормализуется;
- неизвестный geo не выдумывается;
- токен и proxy не попадают в log/result;
- Octo timeout не считается плохой рекламной метрикой;
- профиль не стартует одновременно дважды.

Результат:

- профиль, безопасные discovery/session DTO, catalog/source/session contracts и
  `ProfileService` вынесены в `facebook/profiles`; display/storage naming,
  defaults, enable flags, calibration paths и recovery bounds сохранены;
- Public и Local discovery координируются через `ProfileDiscoveryService`, а
  JSON persistence вынесен в `JsonProfileCatalog`; UUID дедуплицируются как
  между циклами, так и внутри одного API page/result, запись выполняется через
  atomic temporary-file replace;
- Public API возвращает в application layer только UUID/title и намеренно не
  назначает geo по proxy/extra_info hints; normalized geo принимается только из
  Local API connection data и сохраняется write-once после первого надёжного
  наблюдения;
- country normalization сосредоточена в одном модуле, существующие Turkey
  aliases сохранены, пустой geo остаётся `None`, а неизвестное полное название
  не заменяется и не выдумывается;
- `MetricBaseline`, build options, requirements, median builder, window
  comparability и eligibility validation вынесены в `profiles/baseline`;
  `CalibrationPolicy` остаётся во внешнем health compatibility layer и
  преобразуется в узкие baseline options/requirements;
- единый `OctoHttpClient` инкапсулирует Local/Public JSON HTTP, timeout и
  redacted errors; token остаётся только в private request header, HTTP body,
  URL, proxy object и credentials не попадают в exception или profile result;
- Public pagination, Local active discovery, start/stop, headless mismatch
  restart, CDP endpoint mapping и remote-host rewrite разделены между
  `adapters/octo/client.py`, `profiles.py`, `sessions.py` и `mapping.py`;
- standalone runner и orchestrator подключены к новым adapters через небольшие
  compatibility wrappers; старые callable names, CLI help, profiles JSON shape,
  state JSON, tuple результата `get_cdp_endpoint()` и health imports сохранены;
- connection mapping передаёт legacy runner только normalized country и IP,
  поэтому произвольные proxy credentials из Local API больше не могут попасть в
  debug event/run metadata;
- существующий per-profile `flock` оркестратора продолжает запрещать
  одновременный profile cycle и гарантированно останавливает Octo session в
  `finally`; infrastructure timeout/error остаётся health blocker и не входит в
  baseline/advertising degradation signal;
- добавлено 16 unit/contract tests для discovery dedup, active/public authority,
  write-once geo, malformed catalog, baseline parity, Public pagination,
  start/stop/headless restart, safe mapping и redacted HTTP failures; focused
  branch coverage — 92%, полный suite — 488 тестов, общий combined coverage —
  67.54%; strict mypy, Ruff, полный pre-commit, architecture/API/database/CLI
  contracts, frontend build и gitleaks проходят.

Audit observations, не измененные в refactor-only этапе:

- `JsonProfileCatalog` защищает read-modify-write общим process lock и atomic
  replace, но не ставит отдельный cross-process lock на profiles JSON. Production
  orchestrator запускается одним процессом; если появится несколько независимых
  discovery writers, catalog нужно перевести на file lock или database;
- profile execution защищён cross-process `flock` в orchestrator, но прямой
  standalone вызов session manager сам по себе не является distributed lock.
  Вынос durable lease относится к orchestration lifecycle этапу;
- geo остаётся write-once: смена proxy/страны не переписывает существующий
  expected country автоматически. Это защищает baseline от случайного drift,
  но намеренный перенос профиля требует явного config update/reset;
- normalization знает только подтверждённые существующие Turkey aliases;
  полноценное ISO-code mapping нельзя добавлять без списка поддерживаемых Octo
  значений и migration существующих profile configs;
- Octo client сохраняет legacy single-attempt HTTP behavior без retry/backoff.
  Timeout классифицируется как infrastructure failure; retry policy должна быть
  согласована с orchestration capacity и shutdown semantics на последующем
  этапе;
- frontend source/lock не менялись; актуальный `npm audit` по-прежнему сообщает
  6 findings (3 moderate, 3 high), не относящихся к этому backend refactor.

Server, Octo и production runtime не менялись. Старый репозиторий не
использовался. Rollback выполняется revert одного коммита этапа 7.

### Этап 8. `facebook/relevance`

Статус: `COMPLETED` — 2026-08-09

Источники:

```text
services/facebook/relevance.py
services/facebook_relevance_classifier.py
services/facebook_isolated_landing_resolver.py
clients/gemini.py
```

Подэтапы:

1. Models/result parser.
2. Prefilter и scope rules.
3. Prompt construction.
4. Classifier application service.
5. Gemini adapter.
6. Isolated evidence adapter.
7. CLI compatibility wrapper.

Цель:

```text
facebook/relevance/
  service.py
  models.py
  contracts.py
  exceptions.py
  classification/
    service.py
    prefilter.py
    rules.py
    prompt.py
    parser.py
  evidence/
    service.py
    models.py
    policy.py
  adapters/
    gemini.py
    isolated_browser.py
  commands.py
```

Критические тесты:

- все существующие relevance fixtures;
- invalid/model JSON;
- нутра не становится relevant;
- scam/news/celebrity patterns;
- advertiser/domain guard;
- uncertain result и evidence fallback;
- отсутствие профильного landing navigation;
- provider timeout/rate limit/empty response;
- prompt snapshot меняется только осознанно.

Результат:

- создан публичный `facebook/relevance` с отдельными contracts, models,
  exceptions и `RelevanceService`; concrete provider не попадает во внутренние
  слои;
- parsing model JSON, deterministic scope guards, prefilter uncertainty policy,
  prompt construction и artifact lookup разделены на небольшие файлы без
  generic `utils/services/shared` каталогов;
- исходные четыре prompt-варианта сохранены побайтно; их SHA-256 закреплены
  contract-тестом и совпадают с состоянием до переноса;
- сохранен порядок evidence fallback: video может подтвердить relevance, затем
  combined/single screenshots, затем metadata; отрицательный video result не
  блокирует последующую проверку;
- нутра/health, pure gambling, branded broker/prop-firm, enterprise tech,
  gaming и generic redirect exclusions остались deterministic и покрыты
  characterization fixtures;
- `uncertain` разрешен только для prefilter и переводится в `hold`; `deny` и
  unresolved `hold` не могут попасть в authenticated-profile enrichment;
- isolated evidence разделен на URL/SSRF policy, network/context isolation,
  anonymous Facebook post matching, landing capture и browser coordinator;
  сохранены cookie audit, private/meta request blocking и fail-closed summary;
- Gemini SDK перенесен в adapter; timeout, rate-limit и прочие provider errors
  преобразуются в module exceptions, а исходный SDK exception подавляется,
  чтобы response body, prompt или credential не попадали в traceback/logs;
- importer и Taskiq используют новый публичный factory; старые relevance,
  Gemini, classifier и isolated-resolver paths оставлены только минимальными
  compatibility facade/CLI entrypoints для текущего orchestrator contract;
- удалены вторые копии prompt, rules, classifier workflow, Gemini client и
  isolated browser implementation: legacy-файлы сокращены примерно с 2 800
  строк до тонких wrappers;
- focused relevance suite: 104 теста, statement coverage нового модуля 71%;
  расширенный relevance/CLI/architecture gate: 135 тестов;
- полный regression выполнен тремя независимыми группами: 205 + 302 + 10
  Playwright tests, итого 517; объединенное statement coverage `src/app` — 74%;
- Ruff, strict mypy для 35 relevance files, pre-commit, architecture/size/import
  guards, CLI contracts, frontend production build и gitleaks проходят;
- frontend source/lock не менялись; полный `npm audit` по-прежнему сообщает
  известные 6 findings (3 moderate, 3 high), не относящиеся к backend refactor.

Production server, Octo runtime и старый репозиторий не менялись. Rollback
выполняется revert одного коммита этапа 8.

### Этап 9. `facebook/enrichment`

Статус: `COMPLETE`

Источники:

```text
services/facebook_ad_enricher.py
services/facebook/landing_archive.py
relevant-only части facebook_runner.py
```

Подэтапы:

1. RelevantAd input contract.
2. Post resolution.
3. Landing capture.
4. Screenshot capture.
5. Video capture.
6. Archive capture.
7. EnrichmentService.

Цель:

```text
facebook/enrichment/
  __init__.py
  service.py
  models.py
  contracts.py
  exceptions.py
  post/
    matching.py
    urls.py
  media/
    screenshot.py
    archive/
      service.py
      models.py
      policy.py
      naming.py
      html.py
      rewriter.py
      resources.py
      http_capture.py
      browser_capture.py
      browser_index.py
      writer.py
  adapters/playwright/
    post.py
    landing.py
    capture.py
    video.py
    mapping.py
    runtime.py
```

Критические тесты:

- service невозможно вызвать с неподтвержденным candidate;
- landing открывается только после relevant decision;
- archive limits и resource filtering;
- video timeout/static-tail handling;
- вкладки закрываются после каждого ad;
- partial artifact failure не теряет весь result;
- output совместим с ad ingestion.

Результат:

- `RelevantAd.from_raw` и `EnrichmentService` образуют fail-closed boundary:
  `deny`/`hold` отклоняются до вызова browser executor, а `prepare()` явно
  маркирует их `blocked_by_relevance_gate` без активных действий;
- дедупликация candidate, gate summary и invariant
  `active_actions_on_blocked_ads` вынесены из CLI в чистый application service;
- direct Facebook post URL validation и строгий metadata matching отделены от
  Playwright; неоднозначное совпадение по feed fail-closed;
- permalink recovery, post capture, video recording, CTA/landing resolution и
  browser lifecycle разделены на небольшие Playwright adapters; вкладка всегда
  паузится и закрывается в `finally`, а частичный failure сохраняется в result;
- landing capture сохраняет прежний browser-first contract с HTTP fallback,
  cookie/user-agent transfer, limits, resource rejection, HTML/CSS rewrite,
  MHTML, DOM и full-page screenshot; monolith разделен на policy, parser,
  rewriter, HTTP/browser capture и ZIP writer;
- `facebook_runner.py` и relevance landing adapter используют публичный
  `app.facebook.enrichment` API; старые `facebook_ad_enricher.py` и
  `facebook/landing_archive.py` оставлены тонкими CLI/compatibility facades;
- прежние CLI flags, orchestrator module path, JSON field names, archive format,
  output paths и ad ingestion contract сохранены;
- добавлено 15 focused tests для gate/executor boundary, post matching, cleanup,
  archive validity/resource policy и no-candidate/no-browser path;
- focused enrichment/legacy suite: 51 тест, statement coverage нового модуля
  72%; отдельный legacy regression gate: 82 теста;
- полный regression выполнен тремя независимыми группами: 215 + 302 + 10,
  итого 528 тестов; Ruff, strict mypy для 32 enrichment files, architecture,
  size/import guards, CLI contracts, frontend production build и gitleaks
  проходят;
- frontend source/lock не менялись; `npm audit` по-прежнему сообщает известные
  6 findings (3 moderate, 3 high), не относящиеся к backend refactor.

Production server, Octo runtime и старый репозиторий не менялись. Rollback
выполняется revert одного коммита этапа 9.

### Этап 10. `facebook/collection`

Статус: `PENDING`

Источники: passive/candidate части `facebook_runner.py`.

Подэтапы:

1. AdCandidate models.
2. Candidate normalization и deduplication.
3. Feed parsing.
4. Passive media guard.
5. FeedReader Playwright adapter.
6. Passive artifacts.
7. CollectionService pipeline.
8. Legacy runner CLI wrapper.

Цель:

```text
facebook/collection/
  service.py
  models.py
  contracts.py
  exceptions.py
  policies.py
  feed/
    service.py
    models.py
    parser.py
  candidates/
    builder.py
    normalization.py
    deduplication.py
  artifacts/
    models.py
    policy.py

facebook/adapters/playwright/
  session.py
  feed_reader.py
  feed_navigator.py
  selectors.py
  passive_artifacts.py
```

Критические тесты:

- interest-safe pipeline;
- no CTA/landing before relevance;
- duplicate feed cards;
- stuck/small-scroll recovery;
- login-required detection;
- profile/browser cleanup;
- deadline и graceful stop;
- output JSON parity;
- CollectionService вызывает classifier/enricher/writer через contracts.

### Этап 11. `facebook/calibration`

Статус: `PENDING`

Источники:

```text
services/facebook/calibration.py
services/facebook/engagement.py
services/facebook/offer_funnel.py
services/facebook_calibrator.py
calibration decision части services/facebook/health.py
```

Из-за размера этот модуль переносится четырьмя отдельными PR, но считается
одним business-module этапом.

#### 11A. Planning и health decision

- CalibrationPolicy/Decision;
- target pool;
- baseline comparison;
- recovery intensity;
- cooldown/backoff/maintenance;
- pure differential tests legacy/new.

#### 11B. Engagement

- post view contract;
- reaction/follow policy;
- Playwright engagement adapter;
- comments disabled invariant;
- repeated target behavior.

#### 11C. Offer funnel

- funnel policy отдельно от browser implementation;
- prelander/quiz/form adapters;
- domain allowlist;
- identity/redaction;
- submit disabled by default;
- success detection.

#### 11D. CalibrationService и CLI

- target loop;
- session deadline;
- interaction accounting;
- partial target failures;
- legacy CLI wrapper;
- orchestration-facing result.

Цель:

```text
facebook/calibration/
  service.py
  models.py
  contracts.py
  exceptions.py
  planning/
    service.py
    policy.py
    target_pool.py
    intensity.py
  execution/
    service.py
    models.py
  adapters/playwright/
    post_viewer.py
    engagement.py
    offer_funnel.py
    form_filler.py
  commands.py
```

Критические тесты:

- zero/low/drop/maintenance decisions;
- calibration повторяется согласно policy;
- target cap и daily cap;
- работает с 2–3 targets, если больше нет;
- выбирает до 30–50 при recovery;
- не импортирует ads;
- comments не выполняются;
- landing visit выполняется по target;
- submit невозможен без allowlist;
- все tabs/profile закрываются после timeout.

### Этап 12. `facebook/orchestration`

Статус: `PENDING`

Источник: `services/facebook_orchestrator.py`.

Подэтапы:

1. State models и serialization.
2. Scheduling policy.
3. Capacity и profile locks.
4. Profile lifecycle state machine.
5. Recovery transitions.
6. File state adapter.
7. Subprocess runner adapter.
8. OrchestrationService.
9. CLI compatibility wrapper.

Цель:

```text
facebook/orchestration/
  service.py
  models.py
  contracts.py
  exceptions.py
  scheduling/
    policy.py
    scheduler.py
    capacity.py
  lifecycle/
    state_machine.py
    profile_cycle.py
    recovery.py
  adapters/
    file_state_store.py
    subprocess_runner.py
  commands.py
```

Критические тесты:

- max parallel для 1/5/10 профилей;
- независимый lifecycle каждого profile;
- collection и calibration взаимоисключающие;
- 15/45 schedule;
- recovery burst без лишнего cooldown;
- infrastructure retry не влияет на relevance baseline;
- automatic profile discovery;
- restart из сохраненного state;
- SIGTERM/timeout/process-group cleanup;
- один упавший профиль не останавливает остальные;
- calibration result определяет следующий переход;
- Saudi/disabled profile policy сохраняется конфигурацией, а не hardcode.

### Этап 13. Entry points и composition root

Статус: `PENDING`

Изменения:

- `application.py` становится только FastAPI assembly;
- `api.py` только подключает публичные routers;
- `ioc.py` является единственным composition root;
- `worker.py` подключает module tasks;
- `facebook/commands.py` подключает CLI commands;
- старые `services/facebook_*.py` остаются только wrappers до одного release;
- настройки группируются по owning module без изменения env names.

Проверки:

- FastAPI startup/shutdown;
- Dishka graph строится полностью;
- Taskiq imports;
- все старые CLI команды запускаются;
- compose commands остаются рабочими;
- import graph не имеет cycles.

### Этап 14. Удаление legacy и финальный cutover

Статус: `PENDING`

Перед удалением:

- поиск всех imports старых paths;
- полный backend suite;
- frontend build;
- architecture tests;
- clean install из lockfile;
- database migration на копии production schema;
- один manual collection smoke;
- один manual calibration smoke;
- orchestrator smoke минимум с двумя fake и двумя тестовыми профилями;
- сравнение ключевых metrics до/после.

Удаляются:

- `api/modules/*` после переноса;
- общий `services/` после исчезновения consumers;
- `clients/example_service.py` и неиспользуемый template code;
- compatibility wrappers;
- дубли `_load_json`, atomic writes, URL normalization и CLI parsers;
- obsolete docs и placeholder tasks.

Production cutover:

1. Сделать backup DB и orchestration state.
2. Остановить orchestrator без прерывания активного profile process.
3. Развернуть новую версию с прежними env names.
4. Выполнить migrations, если они появились отдельно и были проверены.
5. Запустить API healthcheck.
6. Запустить один профиль в manual collection.
7. Запустить один calibration cycle.
8. Запустить orchestrator с ограниченным parallelism.
9. Проверить state/metrics/media/API.
10. Вернуть полный parallelism.

Rollback:

- остановить новую версию;
- вернуть предыдущий image/commit;
- восстановить orchestration state backup;
- DB rollback нужен только при наличии отдельной schema migration;
- package-only refactor откатывается без изменения данных.

## 15. Definition of Done для одного модуля

Модуль считается перенесенным только если:

- [ ] inventory завершен;
- [ ] characterization tests добавлены до переноса;
- [ ] публичные models/contracts/service определены;
- [ ] dependency direction проверяется автоматически;
- [ ] concrete SDK находятся только в adapters/delivery;
- [ ] legacy и новая бизнес-логика не дублируются;
- [ ] старые imports либо удалены, либо являются тонкими wrappers;
- [ ] module tests проходят;
- [ ] все 317 baseline tests и добавленные тесты проходят;
- [ ] ruff проходит;
- [ ] mypy измененного пакета проходит после этапа 0;
- [ ] frontend build проходит, если затронут API;
- [ ] размеры файлов соответствуют gate;
- [ ] API/CLI/JSON/DB contracts не изменены;
- [ ] security checks пройдены;
- [ ] rollback описан и проверяем;
- [ ] статус этапа обновлен в этом документе.

## 16. Порядок работы в каждом следующем диалоге

Перед началом этапа агент должен:

1. Назвать один конкретный модуль или подэтап.
2. Показать его source-to-target mapping.
3. Выполнить дополнительный архитектурный аудит по разделу 12.1.
4. Перечислить тесты, которые будут добавлены до изменения кода.
5. Подтвердить, что соседние модули не меняются.
6. Выполнить перенос только в `fb-spy-next`.
7. Повторить аудит по итоговому diff.
8. Показать module tests и полный regression result.
9. Обновить этот файл, создать коммит от `axlrose023` и выполнить push.
10. Остановиться перед следующим модулем.

Без отдельного подтверждения нельзя объединять два этапа, менять business policy
или начинать следующий модуль только потому, что предыдущий оказался небольшим.
