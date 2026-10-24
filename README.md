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

## Качество ML

Подготовка данных проверяет движения по наблюдаемому остатку; отсутствие операций
само по себе не считается пропуском. ML прогнозирует бизнес-потоки без внутренних
переводов, но с регулярными платежами — их нельзя добавлять второй раз.

- [Протокол и команды ML](ml/README.md)
- [Проверка прогноза и ограничения](ml/reports/quality.md)
- [Классификатор: отложенные компании и регрессионные примеры](ml/reports/classifier.md)
- [Классификатор: целиком отложенные шаблоны](ml/reports/classifier_templates.md)
- [Контракт и подключение Go](docs/ML_INTEGRATION.md)

Старые показатели 749 прогонов получены до исправления подготовки данных и
с другой политикой предупреждений. Их нельзя сравнивать с новой оценкой без
повторного прогона. Высокие метрики на синтетических слабых метках не доказывают
безошибочность на реальных выписках. В отчётах отдельно указаны ложные сигналы,
короткая история, пропуски и ошибка даты/суммы разрыва.

## Безопасность

- Суммы, ИНН, названия контрагентов и назначения — отдельные типы в
  `backend/internal/domain`, в логах всегда `[REDACTED]` (есть тест).
- ML-сервис наружу не публикуется, пишет в лог только размеры запроса.
- LLM — российский провайдер или обезличивание (152-ФЗ).
