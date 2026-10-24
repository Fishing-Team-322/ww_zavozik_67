# Состояние Go Integration Hub

Проверено по ветке `integration` после объединения с `main` 24.10.2026. Статус относится только к автономному модулю `integrations/`; основной backend развивается отдельно.

| Этап | Статус | Проверяемое основание | Следующий шаг / блокер |
|---|---|---|---|
| 1С: проведённые платежи | LIVE_VERIFIED | `docs/REAL_1C_TEST.md`, `internal/providers/onecodata/*_test.go`; 14 демоплатежей из локальной учебной базы | Сохранять изменения документов, добавить постоянное хранилище |
| 1С: будущие обязательства | MOCK_READY | `internal/providers/onecodata/plans.go`, `plans_test.go`, `testdata/onec_plans_mock.json`; тестирует 350 000 ₽ − 100 000 ₽ = 250 000 ₽, изменение срока, отмену, полную оплату, повторный sync | В живой учебной OData публикации нет коллекций счетов; см. `ONEC_PLAN_MAPPING.md`. До публикации счетов live не подтверждён |
| DaData | MOCK_READY | `internal/providers/dadata/client_test.go`; живой ответ с ключом не подтверждён | Проверить контракт, контроль ИНН, ошибки, кеш; ключ для live отсутствует |
| ФНС: открытые данные | NOT_STARTED | Нет адаптера | Официальный набор, защищённый импорт, датированные сигналы |
| Налоговый календарь | NOT_STARTED | Нет локального движка в Hub | Проверенные правила и тесты для конкретных периодов |
| Wildberries | NOT_STARTED | Нет адаптера | Проверить текущий API, реализовать mock и тесты; кабинет для live отсутствует |
| Ozon | NOT_STARTED | Нет адаптера | Проверить текущий API, реализовать mock и тесты; кабинет для live отсутствует |
| CSV/Excel и ручные планы | PARTIAL | `onecbank` читает формат `1CClientBankExchange`, но не универсальный CSV | Preview, mapping, ошибки строк, идемпотентность |
| Эксплуатация и PostgreSQL | PARTIAL | `cmd/server`, `internal/httpapi`, `internal/store/memory.go`, Dockerfile | PostgreSQL, миграции, tenant isolation, состояние источников |
| Контракт для backend | PARTIAL | `docs/CONTRACT.md`, `docs/BACKEND_MAPPING.md`, `bridge/` | Версионированные DTO, handoff и совместимость |

`IMPLEMENTED` означает реализованный код с тестом, `MOCK_READY` — воспроизводимый ответ синтетического источника, `LIVE_VERIFIED` — подтверждённое обращение к настоящему источнику, `BLOCKED` — невозможность продолжать без внешнего условия, `NOT_STARTED` — отсутствие реализации. Метки этапов будут уточняться по ходу работы.

Текущие интерфейсы, которые сохраняем: `contracts.ImportBatch`, `onecodata.Client.Fetch`, `onecbank.Parser.Parse`, `dadata.Client.Lookup`, маршруты `/healthz`, `/v1/providers`, `/v1/import/onec-bank`, `/v1/sync/onec-odata`, `/v1/enrich/dadata-party`, `/v1/batches/{companyId}`. Новые поля и маршруты добавляются совместимо.
