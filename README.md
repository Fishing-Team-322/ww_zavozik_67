# ww_zavozik_67 — прогноз денежных потоков для малого бизнеса

Кейс банка «Центр-инвест», хакатон «Осень 2026». Сервис прогнозирует остаток
на счёте на 30+ дней, находит кассовые разрывы (дата, сумма, вероятность)
и подсказывает, что сделать.

Архитектура, роли и порядок работ — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

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

## Качество прогноза

Бэктест на датасете кейса: 749 прогонов (6 точек старта с шагом 30 дней,
горизонт 30), модель переобучается раз в месяц только на прошлом, 20% компаний
не видит вообще. Полный отчёт с графиками — [ml/reports/quality.md](ml/reports/quality.md).

| Модель | WAPE 7 / 14 / 30 дней | Ошибка к naive | Покрытие p10–p90 | Разрывы: AUC / полнота |
|---|---|---|---|---|
| **Ансамбль LightGBM + naive** (`auto`) | **20,7 / 30,5 / 47,9%** | **0,85** | 85% | **0,90** / 88% |
| LightGBM глобальная | 21,4 / 31,4 / 50,5% | 0,88 | 81% | 0,88 / 85% |
| Seasonal naive (бейзлайн) | 21,6 / 33,5 / 56,4% | 1,00 | 78% | 0,90 / 91% |
| ETS (Holt-Winters) | 25,9 / 40,9 / 76,7% | 1,32 | 70% | 0,87 / 88% |

Разрыв предсказываем в среднем за ~10 дней. Больше половины движения остатка
за месяц — переводы владельца (займы учредителя, свои средства из другого
банка), их по потокам бизнеса не предсказать; метрика «WAPE (бизнес)» в отчёте
считает ошибку без них.

## Безопасность

- Суммы, ИНН, названия контрагентов и назначения — отдельные типы в
  `backend/internal/domain`, в логах всегда `[REDACTED]` (есть тест).
- ML-сервис наружу не публикуется, пишет в лог только размеры запроса.
- LLM — российский провайдер или обезличивание (152-ФЗ).
