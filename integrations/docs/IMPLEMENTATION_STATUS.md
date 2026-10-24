# Состояние Go Integration Hub

Проверено по ветке `integration` после объединения с `main` 24.10.2026. Статус относится только к автономному модулю `integrations/`; основной backend развивается отдельно.

| Этап | Статус | Проверяемое основание | Следующий шаг / блокер |
|---|---|---|---|
| 1С: проведённые платежи | LIVE_VERIFIED | `docs/REAL_1C_TEST.md`, `internal/providers/onecodata/*_test.go`; 14 демоплатежей из локальной учебной базы | Сохранять изменения документов, добавить постоянное хранилище |
| 1С: будущие обязательства | MOCK_READY | `internal/providers/onecodata/plans.go`, `plans_test.go`, `testdata/onec_plans_mock.json`; тестирует 350 000 ₽ − 100 000 ₽ = 250 000 ₽, изменение срока, отмену, полную оплату, повторный sync | В живой учебной OData публикации нет коллекций счетов; см. `ONEC_PLAN_MAPPING.md`. До публикации счетов live не подтверждён |
| DaData | MOCK_READY / BLOCKED (live) | `internal/providers/dadata/client_test.go`; проверены ИНН/ОГРН, ЮЛ/ИП, 429/5xx, кеш и датированная актуальность; локального `DADATA_API_TOKEN` нет | Живой ответ проверить после появления ключа в локальном окружении; не в чате |
| ФНС: открытые данные | LIVE_VERIFIED (локальный импорт) | `internal/providers/fns/debt.go`, `debt_test.go`, `cmd/inspect-fns`; официальный архив от 25.09.2026: 971 XML, 874002 документа, 1 совпадение по тестовому ИНН, полный разбор за 18 с | Добавить расписание обновления и постоянное хранение сигналов; снимок на 01.09.2026 не является текущим балансом ЕНС |
| Налоговый календарь | IMPLEMENTED (узкая область) | `internal/taxcalendar/usn.go`, `usn_test.go`: подтверждённые сроки УСН на 2026 год, отдельная ручная фиксация суммы | Не поддержаны другие режимы/годы; без подтверждённой суммы обязательство не создаётся |
| Wildberries | MOCK_READY / BLOCKED (live) | `internal/providers/wb/client.go`, `client_test.go`; актуальный Finance API `POST /api/finance/v1/sales-reports/detailed`, RRD-пагинация, 204, финансовые строки без записи в банковский факт | Локального токена/кабинета WB нет; получение фактической выплаты требует отдельной сверки с банком |
| Ozon | NOT_STARTED | Нет адаптера | Проверить текущий API, реализовать mock и тесты; кабинет для live отсутствует |
| CSV/Excel и ручные планы | PARTIAL | `onecbank` читает формат `1CClientBankExchange`, но не универсальный CSV | Preview, mapping, ошибки строк, идемпотентность |
| Эксплуатация и PostgreSQL | PARTIAL | `cmd/server`, `internal/httpapi`, `internal/store/memory.go`, Dockerfile | PostgreSQL, миграции, tenant isolation, состояние источников |
| Контракт для backend | PARTIAL | `docs/CONTRACT.md`, `docs/BACKEND_MAPPING.md`, `bridge/` | Версионированные DTO, handoff и совместимость |

`IMPLEMENTED` означает реализованный код с тестом, `MOCK_READY` — воспроизводимый ответ синтетического источника, `LIVE_VERIFIED` — подтверждённое обращение к настоящему источнику, `BLOCKED` — невозможность продолжать без внешнего условия, `NOT_STARTED` — отсутствие реализации. Метки этапов будут уточняться по ходу работы.

Текущие интерфейсы, которые сохраняем: `contracts.ImportBatch`, `onecodata.Client.Fetch`, `onecbank.Parser.Parse`, `dadata.Client.Lookup`, маршруты `/healthz`, `/v1/providers`, `/v1/import/onec-bank`, `/v1/sync/onec-odata`, `/v1/enrich/dadata-party`, `/v1/batches/{companyId}`. Новые поля и маршруты добавляются совместимо.
