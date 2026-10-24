# 1С → backend → PostgreSQL

Срез 24.10.2026. Банковские факты и входящий счёт с частичной оплатой: **LIVE_VERIFIED** на изолированной опубликованной учебной 1С. Перенос срока и исходящий счёт: **TESTED_WITH_MOCK**; в живой конфигурации нет подтверждённого срока и документа поставщика.

## Путь подключения

Авторизованный пользователь создаёт компанию и источник `onec_odata` через `POST /v1/companies/{companyId}/sources`, затем вызывает существующие `POST /v1/sources/{sourceId}/test` и `/sync`. Конфигурация хранится зашифрованной. `test` читает service document и `$metadata`, проверяет коллекции и поля фактов и необязательного `plan_config`; при несовпадении возвращает `mapping_required` с перечнем `missing`. `sync` читает факты через `bridge.FetchOData` и планы через `bridge.FetchODataPlans`; обе части должны успешно завершиться до записи в одной транзакции PostgreSQL.

`plan_config` задаёт `data_mode`, `organization_ids`, `invoices`, `payments`, реальные имена полей и ключи RUB. Backend использует проверенные `company_id` и `base_url` банковского источника: отдельный адрес для планов не принимается. При ошибке чтения прежний снимок сохраняется. Повтор неизменного счёта не создаёт версию; изменение его содержимого обновляет тот же `planned_events.id` и добавляет `onec_plan_versions`. Банковский факт остаётся в `operations`, поэтому 100 000 ₽ не порождают второй план.

`GET /v1/companies/{companyId}/operations` возвращает факты, `GET /v1/companies/{companyId}/events` — планы. В плане доступны `external_id`, `source_id`, `due_date`, `total_kopecks`, `paid_kopecks`, `remaining_kopecks`, `payment_status`, `forecast_eligible`, `link_status`, `data_mode`, `version`. Чужой пользователь получает 404. Вход прогнозу разрешён только для живого плана с известным сроком, подтверждённой связью и положительным остатком. Живой учебный счёт имеет `due_date=null`, поэтому не выдаётся за датированное поступление.

## Проверки

| Сценарий | Проверенный результат |
|---|---|
| Живая копия 1С → backend → PostgreSQL, факты | 15 операций, включая новое проведённое поступление 100 000 ₽; повтор 0 новых / 15 дублей, API вернул 15 уникальных фактов, чужой пользователь получил 404 |
| Живая копия 1С → backend → PostgreSQL, планы | 7 счетов; повтор 0 новых / 7 дублей; тестовый счёт `35000000` коп. = связанный факт `10000000` + остаток `25000000`, статус `partially_paid`, срок `unknown`, `forecast_eligible=false` |
| Живая отмена в копии 1С → backend → PostgreSQL | После исходного снимка и повтора `DeletionMark=true`: тот же `planned_events.id`, `remaining_kopecks=0`, `paid_kopecks=10000000`, `payment_status=cancelled`, версия 2; в `onec_plan_versions` две версии |
| Моковый OData → backend → PostgreSQL | Перенос срока и отмена обновляют тот же ID и историю до 3 версий; повтор не добавляет дубль; отказ источника сохраняет прежний снимок |
| Изоляция | Две компании с одним внешним ID имеют разные UUID; доступ к чужой компании возвращает 404 |

Живой повторный sync после изменения счёта прошёл в opt-in `TestLiveOneCBackendFacts` с `LIVE_ONEC_CANCEL=1`; он меняет только тестовый счёт изолированной копии и оставляет его помеченным на удаление. Учебная 1С периодически возвращает HTTP 400 «Достигнуто предельное количество подключений к ИБ» после серии запросов. Она не доказывает промышленную устойчивость. Для локального `127.0.0.1` тест явно задаёт `SOURCE_ALLOWED_HOSTS`; в обычной эксплуатации требуются HTTPS, безопасный сетевой доступ и отдельная учётная запись 1С только для чтения.

Запуск: в `backend/` задать `TEST_DATABASE_URL` для тестовой PostgreSQL и выполнить `go test ./internal/httpapi -run TestOneCObligationsBackendE2E -count=1`. Для opt-in живой проверки дополнительно задать `LIVE_ONEC_CONFIG` на `%USERPROFILE%\Documents\1C\AccountingObligationsE2E\backend-live-config.json` вне Git и выполнить `go test ./internal/httpapi -run TestLiveOneCBackendFacts -count=1`. Файл и секреты не коммитить. Перед запуском backend применить миграцию `00004_onec_plan_versions.sql`.
