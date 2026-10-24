# ww_zavozik_67 — прогноз денежных потоков для малого бизнеса

Кейс банка «Центр-инвест», хакатон «Осень 2026». Сервис прогнозирует остаток
на счёте на 30+ дней, находит кассовые разрывы (дата, сумма, вероятность)
и подсказывает, что сделать.

Документация:
- [Продуктовые требования](docs/PRODUCT_REQUIREMENTS.md) — что должен давать продукт.
- [Архитектура](docs/ARCHITECTURE.md) — технические решения, роли и порядок работ.
- [Прогресс](docs/PROGRESS.md) — состояние реализации, доказательства и следующие шаги.
- [Детали реализации](docs/IMPLEMENTATION_NOTES.md) — ограничения и подводные камни.

## Состав

| Папка | Что | Стек |
|---|---|---|
| `api/openapi.yaml` | контракт фронт ↔ бэкенд | OpenAPI 3.0 |
| `proto/` | контракт бэкенд ↔ ML | gRPC, buf |
| `backend/` | API, воркер, бот, бэктест, вся бизнес-логика | Go 1.26 |
| `ml/` | ML-сервис прогноза, обучение, оценка | Python 3.12+ |
| `web/` | фронтенд | на выбор фронтендера |
| `infra/` | docker-compose | Postgres 17 |

## Быстрый старт

Датасет кейса распаковать в `cashflow_dataset_participants/` (в git не коммитится).

```bash
make up                # postgres + ml + api + worker в Docker, API на :8080
curl localhost:8080/healthz
make test              # go test + pytest
make backtest          # бэктест на датасете → ml/data/backtest.csv
```

Перед первым `make up` скопировать `.env.example` в `.env`, задать случайный
`JWT_SECRET` (минимум 32 байта) и пароль Postgres. Compose применяет миграции
отдельным сервисом `migrate` до старта API. Аккаунты, компании, сессии и облачное
состояние описаны в [ACCOUNTS_API.md](docs/ACCOUNTS_API.md).

Без Docker:

```bash
make ml-venv           # один раз
make ml-serve          # ML-сервис на :50051
make backtest ML=localhost:50051
cd backend && go run ./cmd/api
```

Фронту до готовности API — мок по контракту:

```bash
npx @stoplight/prism-cli mock api/openapi.yaml
```

## Как добавлять

- **Эндпоинт:** правим `api/openapi.yaml` → `make gen-api` → реализуем метод на
  `httpapi.Server` (сигнатура — в `unimplemented.gen.go`). Пока метода нет,
  эндпоинт отвечает 501.
- **Прогнозная модель:** класс в `ml/zavozik_ml/forecasters/` с `@register` —
  сразу доступна через gRPC и в `make backtest ML=... ` (`-model <name>`).
- **Источник данных:** тип в `backend/internal/sources/<name>/` +
  `sources.Parsers.Register` или `sources.Pullers.Register` в `init()`.
- **Сценарий, действие, канал уведомлений, LLM:** то же — интерфейс и реестр
  в соответствующем пакете `backend/internal/`.
- **Контракт ML:** правим `proto/` → `make gen-proto`.

Генерация требует `buf`, `protoc-gen-go`, `protoc-gen-go-grpc`:

```bash
go install github.com/bufbuild/buf/cmd/buf@v1.47.2
go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.5
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.5.1
```

## Бейзлайн

Сезонный naive (бутстрап по дню недели), только стохастическая часть, без
регулярных платежей и плановых событий. 150 компаний, 778 прогонов
(6 точек старта с шагом 30 дней), ошибка остатка:

| Горизонт | MAE, ₽ | WAPE | Попадание в коридор p10–p90 |
|---|---|---|---|
| 7 дней | ~0,98 млн | 21% | 81% |
| 14 дней | ~1,5 млн | 33% | 79% |
| 30 дней | ~2,5 млн | 56% | 76% |

Это планка, которую должны побить компонентная модель и ML.

## Безопасность

- Суммы, ИНН, названия контрагентов и назначения — отдельные типы в
  `backend/internal/domain`, в логах всегда `[REDACTED]` (есть тест).
- ML-сервис наружу не публикуется, пишет в лог только размеры запроса.
- LLM — российский провайдер или обезличивание (152-ФЗ).
