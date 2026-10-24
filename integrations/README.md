# Go Integration Hub

Автономный Go 1.25+ модуль для 1С, DaData, ФНС, финансовых отчётов маркетплейсов и CSV. Сервис хранит факты и планы в своей PostgreSQL; основной backend и интерфейс приложения пока не подключены. Актуальные статусы источников — в [отчёте](docs/IMPLEMENTATION_STATUS.md), контракт для backend — в [handoff](docs/BACKEND_HANDOFF.md).

## Импорт банковского файла

Из `integrations/`:

```powershell
Copy-Item .env.example .env
# Заполните в .env два разных случайных значения.
docker compose up --build -d
curl.exe http://127.0.0.1:8091/healthz
curl.exe http://127.0.0.1:8091/v1/providers
curl.exe -H "Authorization: Bearer replace-with-long-random-local-token" -F "file=@testdata/onec_bank_utf8.txt" -F "company_id=demo-company" -F "company_inn=7700000000" -F "company_account=40702810000000000001" http://127.0.0.1:8091/v1/import/onec-bank
```

Разовый запуск без сервера:

```powershell
go run ./cmd/import-onec --file ./testdata/onec_bank_utf8.txt --company-id demo-company --company-inn 7700000000 --company-account 40702810000000000001
```

## Локальная проверка OData

`cmd/mock-onec` — синтетический сервер с формой ответов OData v3. Это **не установленная 1С**. В одном терминале:

```powershell
cd integrations
$env:ONEC_ODATA_USERNAME = 'demo-reader'
$env:ONEC_ODATA_PASSWORD = 'demo-password'
go run ./cmd/mock-onec
```

В другом терминале из `integrations/` задайте те же тестовые значения и запустите чтение:

```powershell
$env:ONEC_ODATA_USERNAME = 'demo-reader'
$env:ONEC_ODATA_PASSWORD = 'demo-password'
go run ./cmd/sync-onec --config ./testdata/onec_odata_mock.json
```

Ожидается `parsed=4`, `accepted=2`, `duplicates=1`, `rejected=1`: две проведённые операции, один повтор и один непроведённый документ. CLI выводит JSON в stdout, обобщённые ошибки — в stderr. CLI не хранит историю между запусками.

Для HTTP синхронизации запустите основной сервер с настройкой источника и отдельным токеном оператора:

```powershell
# Для HTTP синхронизации передайте конфигурацию контейнеру и задайте
# отдельный операторский токен через .env; см. docs/POSTGRES_OPERATIONS.md.
curl.exe -X POST -H "Authorization: Bearer replace-with-long-random-local-token" http://127.0.0.1:8091/v1/sync/onec-odata
```

Сервер читает OData без записи в 1С, сохраняет новые операции и планы в PostgreSQL и отсекает повторы при следующих запросах. `GET /v1/providers` показывает `onecodata: ready` только при загруженной настройке; иначе `not_configured`. Токен нужен для синхронизации, импорта файла, обогащения DaData и просмотра истории. `/healthz` и `/v1/providers` доступны без токена.

## Подключение настоящей 1С

1. Опубликовать информационную базу 1С на веб-сервере с включённым стандартным интерфейсом OData и выделить учётную запись только для чтения. URL должен начинаться с `https://` и заканчиваться `/`, например `https://host/base/odata/standard.odata/`. Для тестов разрешён `http://` только на loopback.
2. Узнать доступные коллекции и названия полей командой `go run ./cmd/inspect-onec --url https://host/base/odata/standard.odata/`. Логин и пароль передаются только через `ONEC_ODATA_USERNAME` и `ONEC_ODATA_PASSWORD`. Команда читает описание OData, не выводит значения записей.
3. Скопировать `testdata/onec_odata_mock.json` вне репозитория и заменить `base_url`, `entity_set`, `fields`, реквизиты компании и `account_map` на реальные значения. `account_map` сопоставляет ключ банковского счёта из ответа 1С с двадцатизначным счётом компании. Для составной ссылки на контрагента можно задать `fields.counterparty_key` и раздел `counterparties` с `entity_set`, `key`, `inn`, `name`; сервис прочитает справочник и подставит доступные реквизиты. Пароли в JSON не записывать.
4. Для HTTP запуска задать `ONEC_ODATA_CONFIG` и `INTEGRATIONS_SYNC_TOKEN`. Проверить ответ на тестовой базе, в том числе даты исполнения, суммы, направления и число отклонённых документов.

Адаптер принимает JSON `value` или OData v3 `d.results`, читает следующие страницы только на том же адресе и в той же коллекции, ставит таймауты и ограничения размера. `Posted=true`, известный банковский счёт, номер, идентификатор, сумма и дата исполнения обязательны. Повторы определяются по идентификатору документа 1С, коллекции и счёту. Исправление уже импортированного документа пока не обновляет старую запись.

Официальное описание [REST/OData 1С](https://v8.1c.ru/platforma/rest-interfeys/) и [публикации информационной базы](https://kb.1ci.com/1C_Enterprise_Platform/FAQ/Development/Integration/How_to_use_the_oData_protocol_when_publishing_an_infobase_to_web_server/). [Бесплатная учебная версия платформы 1С](https://online.1c.ru/catalog/free/28765768/) требует заполнить форму и принять условия; её нельзя выдать за уже готовую рабочую базу с опубликованным OData.

На этой машине установлена учебная платформа 8.3.27.1508 и отдельная учебная «1С:Бухгалтерия» с демонстрационными платежами. Через живой локальный OData адаптер прочитал 14 проведённых платежей: 6 входящих и 8 исходящих. Повторная HTTP синхронизация дала 14 повторов и 0 новых операций. Чтение справочника заполнило 13 имён и 11 ИНН контрагентов. Конфигурация для этой базы хранится вне репозитория в профиле пользователя. Ограничения учебной версии и точные результаты — в [отчёте](docs/REAL_1C_TEST.md).

## Будущие обязательства 1С (пока MOCK_READY)

Адаптер счетов и связанных оплат поддерживает явное сопоставление из строк банковских документов, частичную оплату, изменение срока, отмену и повторную синхронизацию. Демоконфигурация находится в `testdata/onec_plans_mock.json`; для запуска задайте `ONEC_PLAN_CONFIG` и те же `ONEC_ODATA_USERNAME`/`ONEC_ODATA_PASSWORD`, что для `cmd/mock-onec`. Сервер предоставляет `POST /v1/sync/onec-plans` и `GET /v1/planned-events/{companyId}` под токеном оператора. Подробности и причина отсутствия живого импорта счетов: [ONEC_PLAN_MAPPING.md](docs/ONEC_PLAN_MAPPING.md).

## DaData: сведения об организации по ИНН

Адаптер вызывает официальный метод `findById/party` по контрольному ИНН или ОГРН и возвращает тип ЮЛ/ИП, ИНН, КПП для ЮЛ, ОГРН, название, регистрационный статус, доступные даты регистрации/актуальности и время проверки. Регистрационный статус не является оценкой финансовой надёжности. Повторные запросы через сервер кешируются на 24 часа; 429 и временные отказы имеют ограниченные повторы. Он **не создаёт финансовую операцию**. Для живого вызова нужен API-ключ DaData, который сервис выдаёт после регистрации и подтверждения почты. Ключ передаётся только через `DADATA_API_TOKEN`.

Разовый вызов из `integrations/`:

```powershell
$env:DADATA_API_TOKEN = '<ваш ключ в локальной переменной окружения>'
go run ./cmd/lookup-dadata --inn 7707083893
```

Через HTTP сервер также задайте `INTEGRATIONS_SYNC_TOKEN` и отправьте `POST /v1/enrich/dadata-party` с `Authorization: Bearer <токен>` и JSON телом `{"inn":"7707083893"}` или `{"identifier":"<ОГРН>"}`. Пока ключ не задан, `/v1/providers` показывает `dadata: not_configured`. Запросы проверены на локальном тестовом сервере. Успешный живой ответ пока не проверялся: локальной переменной `DADATA_API_TOKEN` нет. [Документация DaData](https://dadata.ru/api/find-party/).

## Docker

Из `integrations/`:

```powershell
Copy-Item .env.example .env
# Заполните INTEGRATIONS_SYNC_TOKEN и INTEGRATIONS_DB_PASSWORD в .env.
docker compose up --build -d
curl.exe http://127.0.0.1:8091/healthz
curl.exe http://127.0.0.1:8091/readyz
```

Compose публикует Hub на `127.0.0.1:8091`, PostgreSQL на `127.0.0.1:5543` и сохраняет БД в именованном томе. Для OData в контейнере нужно отдельно передать переменные окружения и примонтировать файл настройки. `127.0.0.1` внутри контейнера не ведёт на mock или 1С хоста; для реального источника используйте достижимый HTTPS адрес.

## Текущие ограничения

- PostgreSQL переживает перезапуск. Для 1С можно задать `ONEC_SYNC_INTERVAL`; настройка источника пользователем, постоянное хранение секретов и подключение к основному backend ещё не реализованы.
- Токен общий для локального оператора; сервер разрешает только настроенную `INTEGRATIONS_COMPANY_ID` (по умолчанию `demo-company`). Полноценные пользовательские права и несколько компаний требуют backend.
- Файл выписки ограничен 4 MiB, строки — 16 KiB, документы — 10 000. OData: 2 MiB на страницу, до 20 страниц и 4000 записей за синхронизацию и до 4000 контрагентов при включённом разрешении ссылок. Большие базы потребуют фильтра по дате, адресного получения контрагентов и сохранения курсора.
- Поддерживаются UTF-8, UTF-8 BOM и Windows-1251. Ошибки отдельных документов возвращаются кодами в `issues`, без исходных реквизитов; сырые ответы 1С и пароль не попадают в ошибки.
- ФНС проверяет обновления публичного набора задолженности по расписанию и через HTTP; реестровые PDF/XML загружаются через HTTP или CLI. WB и Ozon имеют отдельные адаптеры и mock-тесты; live WB/Ozon/DaData требует локальных ключей.

См. [контракт](docs/CONTRACT.md) и [маппинг backend](docs/BACKEND_MAPPING.md).

## Реестры и открытые данные ФНС

The Hub imports user-supplied EGRUL/EGRIP PDF, XML, and ZIP files without DaData. It also checks the official FNS debt dataset page and imports a newer public snapshot when `FNS_DEBT_INNS` is configured. See [FNS_DIRECT_INTEGRATION.md](docs/FNS_DIRECT_INTEGRATION.md) for setup and API routes, [FNS_SOURCES.md](docs/FNS_SOURCES.md) for the official source and access limits, and [FNS_TEST_RESULTS.md](docs/FNS_TEST_RESULTS.md) for verified test evidence. Registry data and published debt observations are risk context; they do not create cash operations.
