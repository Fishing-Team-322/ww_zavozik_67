# Архитектура и распределение задач

Продуктовые цели, пользовательские сценарии, базовые и расширенные возможности,
безопасность и критерии качества выделены в
[PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md).

Здесь описаны технические решения и организация разработки для этого продукта:
границы компонентов, контракты, хранение, обучение и распределение работы между
6 участниками. Это целевая архитектура, а не перечень уже реализованных функций;
технические решения не следует считать требованиями ТЗ кейса.

Текущее состояние работ — в [PROGRESS.md](PROGRESS.md); конкретные ограничения
и подводные камни кода — в [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md).

Стек: **бэкенд на Go**, **ML (обучение и инференс) на Python**, фронт — на усмотрение фронтендера.

Принципы:
- **Контракты до кода.** `api/openapi.yaml` (фронт ↔ Go) и `proto/` (Go ↔ Python) фиксируем первыми, из них генерируется код с обеих сторон.
- **Всё расширяемое — через интерфейс + реестр.** Новый источник, модель, сценарий, действие, канал уведомлений = один новый тип, без правок ядра.
- **Python-сервис без состояния и без БД.** Получает историю, отдаёт пути прогноза. Всё хранение и бизнес-логика — в Go.

## 1. Структура репозитория

```
api/openapi.yaml            контракт фронт ↔ Go (oapi-codegen на бэке, генератор клиента на фронте)
proto/forecast/v1/          контракт Go ↔ Python (gRPC, buf)
backend/                    Go-модуль
  cmd/api/                  HTTP API
  cmd/worker/               фоновые задачи (River — очередь в Postgres, без Redis)
  cmd/bot/                  Telegram-бот
  cmd/backtest/             бэктест всего пайплайна на исторических данных
  cmd/export/               выгрузка подготовленных данных для обучения (CSV/Parquet)
  internal/domain/          доменные типы — общий язык; чувствительные типы с редакцией в логах
  internal/registry/        общий реестр плагинов (generic)
  internal/config/, logging/  env-конфиг, slog JSON с редакцией по ключам
  internal/dataset/         загрузка датасета кейса для backtest/export
  internal/sources/         адаптеры источников (casecsv — формат датасета кейса, уже есть)
  internal/ingest/          нормализация, дедуп, пропуски
  internal/categorize/      цепочка категоризаторов
  internal/recurring/       поиск регулярных платежей и их проекция вперёд
  internal/events/          плановые события: налоговый календарь, УПД, ручной ввод
  internal/forecast/        сборка прогноза: детерминированные компоненты + вызов ML
  internal/risk/            Монте-Карло-агрегация, разрывы, причины, safe_to_spend
  internal/scenarios/       трансформации «что если»
  internal/actions/         генераторы рекомендаций с эффектом
  internal/notify/          каналы уведомлений
  internal/llm/             адаптер LLM (GigaChat / YandexGPT по умолчанию — 152-ФЗ)
  internal/store/           Postgres (pgx + sqlc)
  internal/httpapi/         api.gen.go из OpenAPI (oapi-codegen, strict std-http) + server.go;
                            unimplemented.gen.go — 501 на всё, что ещё не реализовано
  migrations/               goose
  scripts/                  генерация заглушек
ml/                         Python
  zavozik_ml/serving/       gRPC-сервер
  zavozik_ml/forecasters/   реестр моделей: seasonal_naive (есть), ets, chronos, trx_transformer, ...
  gen/                      код из proto (make gen-proto)
  training/                 претрейн на MBD, дообучение
  eval/                     метрики и графики по выгрузкам из cmd/backtest
  notebooks/
web/                        фронт
infra/                      docker-compose, CI (GitHub Actions)
docs/
```

## 2. Как устроен прогноз и кто что считает

```
                       Go                                         Python (ml/serving)
Источник → sources → ingest → categorize → recurring ─┐
                              events (план) ──────────┤
                                                      ▼
                       forecast: детерминированная часть ───────► gRPC Forecast(history, horizon, n_paths)
                       (регулярные, налоги, кредиты, план)        ◄─── пути стохастической части
                                                      │                (розница, нерегулярное)
                                                      ▼
                       paths = детерминированное + стохастика (по компонентам)
                                                      │
                       scenarios (применяются к компонентам, без повторного вызова ML)
                                                      ▼
                       risk → gaps + причины + safe_to_spend → actions → alerts → notify
```

```
баланс(t) = остаток сегодня
          + Σ регулярные платежи, налоги, кредиты, зарплата   ← Go, объяснимо
          + Σ плановые события из источников (с source)        ← Go, объяснимо
          + стохастическая часть                                ← Python, любая модель
```

Техническое обоснование относительно [продуктовых требований](PRODUCT_REQUIREMENTS.md):
- **Объяснимость:** сохраняем компоненты прогноза для разбора причин разрыва.
- **Быстрые сценарии:** сдвиг события и масштабирование компоненты выполняются в Go без повторного вызова ML. Это выбранный способ быстрого пересчёта, а не отдельное продуктовое ограничение.
- **Отказоустойчивость:** при недоступности Python используем встроенный сезонный naive; результат явно помечаем как упрощённый.

## 3. Контракт Go ↔ Python (proto)

```proto
service Forecaster {
  rpc Forecast(ForecastRequest) returns (ForecastResponse);
  rpc ListModels(Empty) returns (ModelList);           // для /models/quality и выбора модели
}
message ForecastRequest {
  string model = 1;                 // "auto" | "naive" | "ets" | "chronos" | "trx_transformer"
  string industry = 2;              // для холодного старта
  repeated DailyFlow history = 3;   // по дням: inflow/outflow стохастической части, флаги пропусков
  int32 horizon_days = 4;
  int32 n_paths = 5;
}
message ForecastResponse {
  string model_used = 1;
  repeated Path paths = 2;          // n_paths × horizon: inflow, outflow по дням
  repeated Quantiles quantiles = 3; // p10/p50/p90 по дням — для быстрых ответов
  bool low_confidence = 4;          // мало истории
}
```

Python-сторона: реестр `@register("chronos")` — модель автоматически доступна через `ListModels`, в бэктесте и в API (`?model=`).

## 4. Точки расширения в Go

```go
type SourceAdapter interface {           // sources/
    Kind() string                        // "1c_bank_file", "excel", "gsheets", "1c_odata", "fns", ...
    Fetch(ctx context.Context, c Company, since *time.Time) (SourceBatch, error)
}   // SourceBatch{Operations, Planned}; у каждой записи Source — «источник виден пользователю»

type Categorizer interface {             // categorize/  цепочка: правила → LLM для неуверенных
    Categorize(ctx context.Context, ops []Operation) ([]CategoryResult, error)
}   // CategoryResult{Category, Confidence, Method}

type ScenarioTransform interface {       // scenarios/
    Apply(in ForecastComponents) ForecastComponents
}   // DelayCounterparty, ScaleRevenue, AddExpense, ScaleFixedCosts, MoveEvent

type ActionGenerator interface {         // actions/
    Propose(ctx context.Context, gap Gap, fc ForecastContext) ([]Action, error)
}   // RemindClient, ShiftSupplierPayment, OverdraftOffer; эффект = risk со сценарием

type Notifier interface { Send(ctx context.Context, u User, a Alert) error }   // in-app, Telegram
type LLM interface      { Complete(ctx context.Context, req LLMRequest) (LLMResponse, error) }
```

Регистрация — через `init()` в пакете + реестр по `Kind()`.

## 5. Данные (Postgres)

| Таблица | Ключевое |
|---|---|
| `users`, `companies`, `memberships` | пользователь видит только свои компании |
| `sources` | kind, конфиг (секреты шифрованно), статус синка |
| `operations` | факт; `source_id`, `dedup_hash`, `category`, `category_method`, `is_internal` (свои переводы, займы учредителя) |
| `recurring_patterns` | контрагент, период, сумма ± разброс, следующая дата, подтверждён пользователем |
| `planned_events` | план; source, дата, сумма, вероятность, статус `expected/received/missed` |
| `forecast_runs`, `forecast_points` | модель, as_of, дата, p10/p50/p90, компоненты |
| `gaps`, `actions` | дата, сумма, вероятность, причины; рекомендации и эффект |
| `scenarios` | набор трансформаций (JSON) |
| `alerts`, `audit_log` | уведомления; кто и когда смотрел данные |
| River-таблицы | очередь задач |

Реализация [требований безопасности](PRODUCT_REQUIREMENTS.md#5-безопасность-и-качество):
JWT + argon2id; чувствительные типы (`Money`, `INN`, `Purpose`) реализуют
`slog.LogValuer` и в логах пишутся как `[REDACTED]` (+ тест на это).

Механизм инкрементального обновления: новые операции → категоризация только новых
строк → обновление паттернов → пересчёт прогноза от новой даты. Выбранная цепочка
задач в River: `ingest → recompute_forecast → evaluate_alerts → notify`.

## 6. API для фронта (полный — в `api/openapi.yaml`)

```
POST /auth/register | /auth/login
GET  /companies                         POST /companies
POST /companies/{id}/sources            GET  /companies/{id}/sources   POST /sources/{id}/sync
POST /companies/{id}/uploads            (1С-выписка, Excel)
GET  /companies/{id}/operations?category=&from=&to=     PATCH /operations/{id}
GET  /companies/{id}/recurring          PATCH /recurring/{id}
GET  /companies/{id}/forecast?horizon=30&model=&scenario=
     → {as_of, safe_to_spend, headline, points:[{date,p10,p50,p90,components}], gaps:[...]}
GET  /companies/{id}/gaps/{gap_id}      → причины (waterfall) + actions с эффектом
GET  /companies/{id}/events             POST /events   POST /events/parse {text}
PATCH /events/{id}                      (перенос даты — drag&drop)
GET/POST /companies/{id}/scenarios      GET /companies/{id}/scenarios/{sid}/compare
GET  /companies/{id}/plan-fact?granularity=day|week
GET  /companies/{id}/counterparties
GET  /companies/{id}/retro              («мы бы вас предупредили»)
GET  /companies/{id}/alerts             POST /me/telegram/link
GET  /models/quality
```

## 7. Обучение и проверка качества

- **Обучение (Python):** претрейн энкодера последовательностей на MBD (~950M транзакций корпоративных клиентов, ~12 мес., поля `event_time, amount, currency, event_type/subtype, src/dst_type*`; остатков и текста нет) → дообучение на прогноз дневных притоков/оттоков стохастической части с квантилями. Любые другие данные — сюда же.
- **Разделение обучения и оценки:** датасет кейса остаётся отложенной выборкой согласно [требованиям качества](PRODUCT_REQUIREMENTS.md#5-безопасность-и-качество).
- **Бэктест всего пайплайна — `cmd/backtest` (Go):** скользящие точки старта по датасету кейса, гоняет ровно тот код, что в проде, вызывая ML-сервис. Пишет результаты в Parquet → `ml/eval/` строит метрики и графики.
- **Оценка:** `ml/eval/` рассчитывает метрики остатка и разрывов из [продуктовых требований](PRODUCT_REQUIREMENTS.md#5-безопасность-и-качество). Порог и правила разметки разрывов ещё нужно согласовать; технический пайплайн не должен неявно задавать их.
- **Быстрые эксперименты ML без Go:** `cmd/export` выгружает стохастическую часть рядов (потоки минус детерминированные категории) → обучаешь и сравниваешь модели в ноутбуках.

## 8. Кто что делает

| Кто | Владеет | Конкретно |
|---|---|---|
| **Тимлид / ML** | `ml/`, `proto/` | proto-контракт (день 1); gRPC-сервер с реестром; бейзлайны naive/ETS; Chronos; трансформер (MBD → дообучение); `ml/eval`, метрики; страница качества. Плюс OpenAPI-ревью и приоритеты |
| **Бэк 1 — данные** | `sources/`, `ingest/`, `categorize/`, `recurring/`, `cmd/export` | адаптеры: 1CClientBankExchange, Excel (excelize), ФНС открытые данные, проверка контрагента; дедуп через остаток, пропуски, флаг внутренних переводов; правила категоризации + LLM-фолбэк; поиск регулярных платежей; рейтинг дисциплины контрагентов |
| **Бэк 2 — продуктовая логика** | `events/`, `forecast/`, `risk/`, `scenarios/`, `actions/`, `cmd/backtest` | налоговый календарь, плановые события из УПД, ввод фразой (через `llm/`); сборка компонент + gRPC-клиент + встроенный бейзлайн-фолбэк; разрывы + причины, `safe_to_spend`; сценарии; действия; план-факт; ретро; бэктест; адаптер Google Sheets |
| **Бэк 3 — платформа** | `cmd/api`, `cmd/worker`, `cmd/bot`, `httpapi/`, `store/`, `notify/`, `infra/` | OpenAPI-скелет (день 1) + oapi-codegen; auth; Postgres, sqlc, goose; River и цепочка задач; audit_log и редакция логов; Telegram-бот; docker-compose (api, worker, bot, ml, postgres); CI (golangci-lint, go test, pytest); деплой; адаптер 1С OData (если поднимется база) |
| **Фронт** | `web/` | стек на выбор; пользовательские разделы и сценарии — в `PRODUCT_REQUIREMENTS.md`, разделы 2–4. До API — мок-сервер из OpenAPI (Prism) |
| **Человек с ChatGPT** | промпты, оценка, питч | промпты для `llm/` (категоризация, разбор фразы, объяснения, письма клиенту); золотая разметка 300–500 операций; демо-компании; тексты интерфейса; тест-кейсы и ручное QA; попытка поднять 1С с OData; презентация и схема архитектуры |

## 9. Порядок, чтобы никто не ждал

1. **Старт (1–2 часа, все вместе):** `internal/domain`, `api/openapi.yaml`, `proto/`, скелет репо, docker-compose с пустыми сервисами. Дальше каждый в своей папке.
2. **Вертикальный срез:** выписка → правила категоризации → регулярные платежи + встроенный naive → API → график на главной. Работает раньше всего остального.
3. **Параллельно:** каждый улучшает свой модуль за своим интерфейсом. ML-сервис подключается, когда готов; трансформер становится `auto` только если выигрывает в бэктесте.
4. **Расширения:** порядок реализации возможностей из [продуктового плана](PRODUCT_REQUIREMENTS.md#4-расширенные-возможности-исходного-плана): разрыв с причинами и действиями → safe_to_spend → сценарии/календарь → ретро → Telegram → план-факт → интеграции сверх базовых.
5. **Финал:** заморозка фич, прогоны демо, резервное видео.
