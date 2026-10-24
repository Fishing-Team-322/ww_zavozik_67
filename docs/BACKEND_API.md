# API аккаунтов и финансов

`max-back` обновлена из `main`, включая актуальный ML и интеграции. Финансовый API
подключён к существующим Go-пакетам и Postgres. Контракт:
[`api/openapi.yaml`](../api/openapi.yaml). Все 96 маршрутов документа «Экраны и API
Завозик» включены; всего 106 операций с учётом системных методов, облачного состояния,
совместимых путей и скачивания архива. Это покрытие маршрутов; ограничения ниже.

## Запуск

1. Скопировать `.env.example` в `.env`; задать `JWT_SECRET`, пароль Postgres,
   публичные адреса и cookie-режим. `.env` автоматически читает Compose, Go — нет.
2. Для сохранения конфигурации источников задать `DATA_ENCRYPTION_KEY`: base64 от
   32 случайных байтов, одинаковый для API и worker. Сохранить его с резервной
   копией БД: потеря ключа делает пароли источников недоступными.
3. `make up` применяет миграции `00001..00003` перед API и worker. Без Compose из
   `backend/` выполнить `go run ./cmd/migrate`, затем в отдельных процессах
   `go run ./cmd/api` и `go run ./cmd/worker` с одинаковым окружением.
4. Для ML указать `ML_ADDR`. При сетевом отказе используется seasonal naive с
   `fallback_used=true`, `low_confidence=true` и предупреждением. Неверные входные
   данные и недостаточность наблюдений дают 400/422.

Go-образ собирается **из корня репозитория**: `docker build -f backend/Dockerfile .`.
Контекст нужен для зависимости `integrations/bridge` и отчётов ML. Compose обновлён.
Перед миграциями существующей БД сохранить копию; Down удаляет новые продуктовые данные.

## Общий контракт

- Авторизация: `Authorization: Bearer <access_token>`. Аккаунты/OAuth/сессии/сброс
  пароля описаны в [ACCOUNTS_API.md](ACCOUNTS_API.md).
- Контейнер данных — **компания**. Владелец работает со своими компаниями.
  Чужой и отсутствующий ресурс дают одинаковый 404. `company_id`, автор, ID и
  служебные поля назначает сервер.
- Деньги — рубли, положительная `amount`, отдельное `direction: in|out`, до двух
  знаков после запятой. В компонентах прогноза расход имеет знак минус.
  Даты — `YYYY-MM-DD`, месяц — `YYYY-MM`, время — RFC3339 UTC.
- Пустые коллекции — `[]`; неизвестные метрики — `null`. Ошибки:
  `{"code":"machine_code","message":"сообщение"}`. Нет обёртки data.
- Страничные ответы: `{"items":[],"next_cursor":null}`, `limit` 1–1000,
  непрозрачный `cursor`. Компании, события, счета и небольшие коллекции — массивы.
  Конкретные формы и допустимые поля запросов/ответов описаны в OpenAPI.
- PATCH проверяет внутреннюю ревизию записи: параллельное изменение — 409.
  Облачный JSON использует отдельный `version`.

## Импорт, источники и задания

`POST /v1/companies/{id}/uploads` принимает multipart с одним полем `file`:
CSV (UTF-8/Windows-1251, запятая/точка с запятой/табуляция), XLSX (первый лист),
1CClientBankExchange (UTF-8/Windows-1251). До 4 MiB, 10000 строк данных,
100 столбцов. Для выписки 1С нужен ИНН компании; счёт извлекается из файла.

CSV/XLSX: `date`, `amount`, `direction`, `counterparty_name`, `counterparty_inn`,
`purpose`, `balance_eod` или русские аналоги. Дата ISO/DD.MM.YYYY.
`balance_eod` — известный остаток **на конец дня**, одинаковый для строк одного дня.
Неизвестные заголовки дают 200 `{upload_id,detected_format,needs_mapping:true}`:
прочитать preview, передать mapping доменного поля к названию столбца. Для знаковой
суммы сопоставить `sign` тому же столбцу вместо `direction`.

Готовая загрузка, sync, экспорт и retrain дают 202 Job. Поллинг
`GET /v1/jobs/{id}`: `queued|running|done|failed`, `progress`, `error`, `result_ref`.
Очередь постоянная в Postgres: SKIP LOCKED, ограничение времени работы, возврат
просроченного задания другому worker. Обычная ошибка завершает задание как failed;
повтор sync доступен через API. Отчёт импорта содержит добавленные/отклонённые/
повторные строки. Повтор файла не добавляет те же факты; одинаковые легитимные
платежи внутри файла сохраняются. Финансовый дедуп использует проверки остатка из main.

Настройки источников шифруются AES-256-GCM; пароли и токены не выдаются в API,
аудите или пользовательском экспорте. Тип существующего источника не меняется.
Удаление требует JSON `{keep_data:true|false}`.

| kind | Конфигурация и доступ |
|---|---|
| manual / upload / excel / onec_bank_file | Файловый поток; `/test` проверяет готовность загрузки, `/sync` требует файл (409) |
| onec_odata | `config` по примеру `integrations/testdata/onec_odata_mock.json` + `username`, `password`. company_id/ИНН привязывает сервер. `SOURCE_ALLOWED_HOSTS` — точный host:port 1С; HTTP разрешён адаптером только на loopback |
| gsheets | `spreadsheet_id`, необязательный `range` (по умолчанию A1:Z10001), `access_token` или `api_key`; фиксированный Google Sheets API. Нужны права чтения таблицы. Обновления истёкшего access token здесь нет |
| fns | `DADATA_API_TOKEN` задаётся оператором. `/v1/fns/lookup?inn=...` читает сведения через DaData; прямого подключения к ФНС и налоговых долгов нет |

Сетевой `/test` вызывает адаптер. Sync выполняется по запросу; периодического
планировщика опроса нет. При отсутствующем ключе/провайдере возвращается 503.
Экспорт операций — XLSX с фильтрами списка; текстовые ячейки записываются строками,
не формулами. Экспорт компании — ZIP JSON, доступный владельцу по `result_ref`.

## Расчёты и ограничения

Прогноз начинается после последней фактической даты выписки (`as_of`), требует
наблюдаемую историю и известный остаток. Нет переноса остатка через неизвестное
движение. Старая выписка даёт warning. Сохраняются `model_used`, `model_version`,
`flow_scope`, `warnings`, `fallback_used`, `low_confidence`. Календарь РФ 2024–2027
совпадает с ML; вне диапазона используется будний/выходной день.

ML с `business_without_internal_transfers` уже включает регулярные зарплаты,
налоги и аренду. Выявленные регулярные платежи и документы по умолчанию видны в
календаре, **не прибавляясь к ML повторно**. Ручное разовое событие по умолчанию
`additional=true`; для нового счёта/договора вне ожидаемого потока явно задать
`additional:true`. Документ и события сохраняются одной транзакцией; управляемое
событие редактируется через документ.

Ручные регулярные платежи проецируются как дополнительные. Детектор предлагает
шаблоны после минимум четырёх похожих наблюдений: это эвристика для подтверждения.
Коррекция суммы/отключение выявленного шаблона меняет календарь; уже выученный
исторический регулярный поток ML этим не переобучается.

Дополнительный платёж с `0 < probability < 1` разыгрывается целиком в отдельных
путях, а не как гарантированная дробная сумма. Пользовательские вероятности
независимы и не калиброваны по внешней выборке. Сценарии используют те же пути
и глубокую копию базового прогноза. Поддержаны scale_revenue, add_expense,
move_event, delay_counterparty, scale_fixed_costs. Задержка переносит известные
плановые поступления клиента; без них — 422. Постоянные расходы меняются по
известному графику. Preview ничего не сохраняет.

Рекомендации оценивают перенос событий и план привлечения средств. `apply`
идемпотентно меняет план; кредит не оформляется, сообщения не отправляются.
План-факт сопоставляет уникальный факт по контрагенту, направлению, сумме и окну
±3 дня. Неоднозначные совпадения остаются несопоставленными. Платёжная дисциплина
считается только по оплаченным сопоставленным счетам клиентам; без истории — null.
Ретроспектива считает упреждение только по прогнозам, сохранённым до события.
Точность накапливается после появления факта.

`/taxes` проецирует подтверждённые регулярные налоговые платежи. Расчёта по
налоговой ставке, декларации и автоматического определения режима нет.
Парсер русской фразы — правила; возвращает проверяемый черновик с confidence.
LLM не подключена. Уведомления создаются в приложении; бот и внешняя рассылка
требуют отдельной реализации.

## Администрирование

Admin проверяется по БД при каждом запросе; роль нельзя задать при регистрации.
Просмотр компании и изменение статусов аудируются. Блокировка отзывает сессии
и запрещает вход, включая ранее выданный JWT. Admin может повторить sync без
получения пароля источника.

Качество моделей/классификатора читается из опубликованных `ml/reports/metrics`;
это не live-качество каждой компании и не независимая ручная gold-разметка.
Drift — ошибка сохранённых прогнозов против наблюдаемых остатков; неизвестные
порог и решение о переобучении возвращаются null.

`retrain` требует **отдельный существующий сервис обучения** `TRAINING_URL`
(HTTPS/loopback HTTP) и при необходимости `TRAINING_TOKEN`. Worker посылает
POST `{"model":"auto"}`, ждёт HTTP 200 `{"trained":true,"model_version":"..."}`.
Только подтверждённое обучение даёт done. Текущий ML gRPC обучения не предоставляет;
без сервиса — 503. Backend не создаёт/разворачивает тренер автоматически.

Сигналы — объяснимые эвристики крупных расходов (медиана + нижний порог),
а не вердикт о мошенничестве. Admin рассматривает/закрывает сигнал с решением.
Внешние fraud-проверки и сведения о налоговых долгах не выдумываются.

## Проверки

Из backend: `go test ./...`, `go vet ./...`; из integrations: `go test ./...`.
Для SQL/HTTP тестов задать `TEST_DATABASE_URL` на тестовый Postgres. Тесты создают
временную схему и удаляют только её. CI использует Postgres 17, race detector,
проверку воспроизводимости генерации и сборку Compose.

`TestProductEndToEnd`: импорт → операции → прогноз → сценарии/действия,
документы в календаре, XLSX/ZIP, доступ чужой компании, admin и блокировка.
`TestProductSourceAdaptersAndRecovery`: mapping, XLSX, UTF-8/BOM/Windows-1251 1С,
Go OData против локального HTTP-сервера, шифрование, неверный ключ, запрещённый
host, подтверждение тренера и восстановление worker. Production-доступы к
внешним сервисам этими тестами не проверяются.

## Реестр маршрутов

Все маршруты ниже имеют обработчики; доступность зависит от данных, авторизации
и указанных выше сервисов. Реестр сформирован из OpenAPI.

| Метод | Путь | operationId |
|---|---|---|
| GET | /healthz | getHealth |
| GET | /v1/models | listModels |
| GET | /v1/models/quality | getModelQuality |
| POST | /v1/auth/register | register |
| POST | /v1/auth/login | login |
| GET | /v1/companies | listCompanies |
| POST | /v1/companies | createCompany |
| GET | /v1/companies/{companyId}/sources | listSources |
| POST | /v1/companies/{companyId}/sources | createSource |
| POST | /v1/sources/{sourceId}/sync | syncSource |
| POST | /v1/companies/{companyId}/uploads | uploadStatement |
| GET | /v1/jobs/{jobId} | getJob |
| GET | /v1/companies/{companyId}/operations | listOperations |
| PATCH | /v1/operations/{operationId} | updateOperation |
| GET | /v1/companies/{companyId}/recurring | listRecurring |
| POST | /v1/companies/{companyId}/recurring | createRecurring |
| PATCH | /v1/recurring/{patternId} | updateRecurring |
| DELETE | /v1/recurring/{patternId} | deleteRecurring |
| GET | /v1/companies/{companyId}/counterparties | listCounterparties |
| GET | /v1/companies/{companyId}/forecast | getForecast |
| GET | /v1/companies/{companyId}/gaps/{gapId} | getGap |
| GET | /v1/companies/{companyId}/retro | getRetro |
| GET | /v1/companies/{companyId}/plan-fact | getPlanFact |
| GET | /v1/companies/{companyId}/events | listEvents |
| POST | /v1/companies/{companyId}/events | createEvent |
| POST | /v1/companies/{companyId}/events/parse | parseEvent |
| PATCH | /v1/events/{eventId} | updateEvent |
| DELETE | /v1/events/{eventId} | deleteEvent |
| GET | /v1/companies/{companyId}/scenarios | listScenarios |
| POST | /v1/companies/{companyId}/scenarios | createScenario |
| GET | /v1/companies/{companyId}/scenarios/{scenarioId}/compare | compareScenario |
| GET | /v1/companies/{companyId}/alerts | listAlerts |
| POST | /v1/auth/refresh | refresh |
| POST | /v1/auth/logout | logout |
| POST | /v1/auth/password/forgot | forgotPassword |
| POST | /v1/auth/password/reset | resetPassword |
| GET | /v1/auth/providers | listAuthProviders |
| GET | /v1/auth/oauth/{provider}/start | startOAuth |
| GET | /v1/auth/oauth/{provider}/callback | finishOAuth |
| GET | /v1/me | getMe |
| PATCH | /v1/me/password | changePassword |
| GET | /v1/me/sessions | listSessions |
| DELETE | /v1/me/sessions/{sessionId} | revokeSession |
| GET | /v1/companies/{companyId} | getCompany |
| PATCH | /v1/companies/{companyId} | updateCompany |
| DELETE | /v1/companies/{companyId} | deleteCompany |
| GET | /v1/companies/{companyId}/state | getCompanyState |
| PUT | /v1/companies/{companyId}/state | putCompanyState |
| GET | /v1/fns/lookup | lookupFNS |
| POST | /v1/companies/{companyId}/export | exportCompany |
| GET | /v1/jobs/{jobId}/download | downloadJob |
| GET | /v1/companies/{companyId}/dashboard | getDashboard |
| GET | /v1/companies/{companyId}/forecast/days/{date} | getForecastDay |
| POST | /v1/companies/{companyId}/forecast/preview | previewForecast |
| GET | /v1/companies/{companyId}/forecast/accuracy | getForecastAccuracy |
| POST | /v1/companies/{companyId}/gaps/{gapId}/simulate | simulateGap |
| POST | /v1/actions/{actionId}/apply | applyAction |
| GET | /v1/companies/{companyId}/operations/summary | summarizeOperations |
| POST | /v1/companies/{companyId}/operations/recategorize | recategorizeOperations |
| GET | /v1/companies/{companyId}/operations/export | exportOperations |
| GET | /v1/categories | listCategories |
| PATCH | /v1/scenarios/{scenarioId} | updateScenario |
| DELETE | /v1/scenarios/{scenarioId} | deleteScenario |
| GET | /v1/companies/{companyId}/invoices | listInvoices |
| POST | /v1/companies/{companyId}/invoices | createInvoice |
| PATCH | /v1/invoices/{invoiceId} | updateInvoice |
| DELETE | /v1/invoices/{invoiceId} | deleteInvoice |
| GET | /v1/companies/{companyId}/contracts | listContracts |
| POST | /v1/companies/{companyId}/contracts | createContract |
| PATCH | /v1/contracts/{contractId} | updateContract |
| DELETE | /v1/contracts/{contractId} | deleteContract |
| PATCH | /v1/sources/{sourceId} | updateSource |
| DELETE | /v1/sources/{sourceId} | deleteSource |
| GET | /v1/sources/{sourceId} | getSource |
| POST | /v1/sources/{sourceId}/test | testSource |
| GET | /v1/uploads/{uploadId}/preview | previewUpload |
| POST | /v1/uploads/{uploadId}/mapping | mapUpload |
| GET | /v1/companies/{companyId}/imports | listImports |
| GET | /v1/imports/{importId} | getImport |
| GET | /v1/companies/{companyId}/calendar | getCalendar |
| GET | /v1/scenario-presets | listScenarioPresets |
| POST | /v1/companies/{companyId}/scenarios/preview | previewScenario |
| GET | /v1/scenarios/{scenarioId}/compare | compareSavedScenario |
| GET | /v1/companies/{companyId}/taxes | getTaxes |
| GET | /v1/companies/{companyId}/plan-fact/missed | getMissedPlanFact |
| GET | /v1/companies/{companyId}/counterparties/{cpId} | getCounterparty |
| GET | /v1/companies/{companyId}/counterparties/concentration | getConcentration |
| PATCH | /v1/alerts/{alertId} | updateAlert |
| POST | /v1/companies/{companyId}/alerts/read-all | readAllAlerts |
| GET | /v1/admin/overview | getAdminOverview |
| GET | /v1/admin/users | listAdminUsers |
| PATCH | /v1/admin/users/{userId} | updateAdminUser |
| GET | /v1/admin/companies | listAdminCompanies |
| GET | /v1/admin/companies/{companyId} | getAdminCompany |
| GET | /v1/admin/integrations | listAdminIntegrations |
| GET | /v1/admin/integrations/stats | getAdminIntegrationStats |
| POST | /v1/admin/integrations/{sourceId}/retry | retryAdminIntegration |
| GET | /v1/admin/models | listAdminModels |
| GET | /v1/admin/models/drift | getModelDrift |
| POST | /v1/admin/models/{name}/retrain | retrainModel |
| GET | /v1/admin/classifier | getClassifierQuality |
| GET | /v1/admin/antifraud/signals | listSignals |
| GET | /v1/admin/antifraud/signals/{signalId} | getSignal |
| PATCH | /v1/admin/antifraud/signals/{signalId} | updateSignal |
| GET | /v1/admin/antifraud/stats | getSignalStats |
| GET | /v1/admin/audit | listAudit |
