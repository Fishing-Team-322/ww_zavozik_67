# ПУЛЬС V2 — отчёт о ремонте и локальной приёмке, 24.10.2026

Рабочая ветка — `integration`. Приложение пересобрано, пользовательские сценарии проверены на локальных контейнерах и PostgreSQL. Это **не подтверждение готовности всех внешних live-интеграций или публичного сервера**: для них ниже перечислены конкретные ограничения. В `main` ничего не влито.

## Что исправлено

| Неисправность | Изменение | Доказательство |
|---|---|---|
| `counterparty_id=` ломает generated UUID binding | Совместимость одиночного пустого optional UUID до binding; неверный непустой UUID даёт человеческий 400. Общий frontend query helper исключает пустые значения | PG `TestCompletionSelfServiceAndOptionalFilters`, browser `completion-p0.spec.mjs`: absent/empty/valid/invalid через настоящий Next proxy |
| `unread=` ломает boolean binding; `false` не фильтрует прочитанные | Пустое считается отсутствием; 400 для неверного значения; реализован фильтр false и пункт «Прочитанные» | Те же API тесты: absent/empty/true/false/invalid; UI чтение/снятие прочтения и переключение фильтров |
| Непонятно, нужен ли администратор для новой компании | Форма доступна обычному пользователю; объяснён workspace; ИНН необязателен, права выдаются только создающему owner | Регистрация в браузере → новая компания; два разных пользователя с одним ИНН получают разные company ID, чужие данные 404 |
| ИНН 6164138512 ошибочно похож на официальный | Контрольная цифра на frontend/backend. 6164138512 отклоняется, 6164138513 принимается; существующий ошибочный профиль пользователя автоматически не переписывается | Unit INN, PG onboarding, browser P0; сверка официального PDF |
| Резерв воспринимается как банковский остаток | Переименован в «Защитный резерв» и объяснён в создании/настройках. Сохранены null/0/измеренный остаток; ЕГРЮЛ не создаёт операций | PG и browser P0: unknown/null, реальный 0, 123456,78; XLSX 0; 1С OData без остатка показывает недостаток данных |
| PDF ФНС нельзя загрузить через пользовательский путь | Отдельный preview/confirm/history PDF/XML/ZIP, явная привязка, профиль контрагента. Банковский импорт объясняет правильный раздел | Browser `registry.spec.mjs`, opt-in Go с официальным PDF; 0 новых операций и null balance после документа |
| OData воспринимается как ключ, сложный ручной счёт | Сетевой/файловый сценарии, пошаговая инструкция, discovery организаций и счетов по ИНН, выбор счёта, advanced только для ручного номера | Live browser на учебной базе; исправлена найденная при прогоне ошибка: URL/ИНН были скрыты вместе с ручным счётом |
| Остальные адаптеры не соединены с пользовательским UI | Формы WB/Ozon, отдельные отчёты; Sheets preview/mapping; scoped ФНС snapshot; честный каталог возможностей | Browser sandbox + PG: сохранение, sync, повтор, ротация ключа, изоляция, отсутствие банковского факта от маркетплейсов |
| Новые credentials могли оставлять старый зелёный статус | PATCH config объединяет новые значения с зашифрованными прежними, повторно валидирует; статус pending. Повторное включение также pending | PG tests и UI ротации WB; секрет не возвращается и не лежит открытым в DB |
| Обновления сессии блокируют вход при общем auth budget | Отдельные бюджеты: credentials 30/мин/IP, refresh/logout 120/мин/IP. Подложный XFF не определяет client IP | Повтор общего browser run после выявленного 429 прошёл; `TestSessionTrafficKeepsCredentialRateBudgetIsolated`; Caddy smoke |
| Риск SSRF через DNS OData | Operator exact allowlist остаётся обязательным; bridge проверяет DNS на каждом dial и соединяется с конкретным проверенным IP/портом; proxy env и redirects исключены | Bridge DNS tests; live 1С через явно разрешённый loopback; private/metadata/CGNAT DNS и смена порта отклоняются |

## Сборка и сохранность

- Последний коммит приложения и реально запущенные API/worker/frontend/Hub: **`a7cb248943da569defa88849b0f41c65a734ac1c`**. Следующий коммит содержит только этот отчёт и доказательства, код приложения не изменяет.
- SHA проверен по OCI `org.opencontainers.image.revision` всех четырёх контейнеров; frontend `/build-info.json` и API `X-App-Revision` дают тот же идентификатор. Финальные production builds выполнены из этой ревизии. IAB отдельно отказал в навигации к JSON-странице (`blocked by client`); это не считается успешной ручной проверкой IAB. Полноценные пользовательские тесты выполнены в Edge/Playwright.
- Frontend `.next/BUILD_ID`: **`V9bBIRHUkgGgUoxrsbnsQ`**. Финальный общий прогон на этой сборке: **8 PASS**, отдельно sandbox **1 PASS**, restart/recovery **1 PASS** — всего 10 самостоятельных сценариев. Дополнительный opt-in live-прогон частичной оплаты/отмены также PASS. После завершения `/healthz` вернул `status=ok, ml=ok`, API/Hub readiness — `ready`.
- Основной локальный сайт `http://localhost:3000`, API `127.0.0.1:8080`; Caddy проверен на локальном HTTP `127.0.0.1:8082`. Hub `127.0.0.1:8091`. PostgreSQL основной платформы не публикует порт.
- Отдельный mock-проект `puls-integration-sandbox`, сайт 3001/API 8081, отдельный volume. Основной сайт не переключался на mock.
- Применена миграция `00005_registry_documents.sql`; БД версии 5. До миграции сохранены custom dumps платформы и Hub в `%TEMP%/puls-v2-backups-20261024-193037`; секреты и оригинальные документы вне Git.
- Восстановление **отдельной** БД `puls_v2_restore_20261024`: 49 пользователей, 36 компаний, 2370 операций. Восстановление `puls_hub_restore_20261024`: 13 операций, 13 рисков, 3 состояния наборов. Рабочие базы не заменялись, `DROP DATABASE`, `down -v` и очистка volumes не выполнялись.
- Browser restart-тест на финальной ревизии сохранил **85 пользователей, 80 компаний, 3390 операций, 135 событий, 47 источников, 120 версий 1С, 117 документов**. Это суммарные записи нескольких E2E-прогонов, не результат одного sync. Проверено совпадение до/после restart, сохранение cookie-сессии и выполнение queued export после возвращения worker.

## Настоящие источники и финансовые числа

### Официальный PDF ФНС

Локальный файл `ul-1226100018561-20261024122126 — копия.pdf`, полученный пользователем с сервиса ФНС: ООО «МАДРИГАЛ», ИНН **6164138513**, ОГРН **1226100018561**, дата **24.10.2026**, 16 страниц с текстовым слоем. Preview не сохраняет профиль до confirm. Подтверждение и повтор проверены в браузере/API, повторная запись не добавляется. Документ может быть привязан к workspace только при совпадении ИНН; иначе доступна привязка контрагента. Ownership и банковский счёт не подтверждаются; подпись **NOT_VERIFIED**. Оригинал PDF и полный профиль в Git не включены, скриншот профиля замаскирован.

### 1С

Только отдельная учебная копия `/codexobligations`, исходная бухгалтерская база не заменялась. Реально получены **15 фактических операций, 7 счетов**, повтор фактов дал 0 новых и 15 дублей. Сроки части счетов не опубликованы: они остаются undated и не включаются в точечный прогноз. Денежный остаток из банковских документов OData не выдумывается.

В изолированной копии тестовый счёт 350000 ₽ временно активирован: связанные проведённые платежи 100000 ₽, остаток 250000 ₽, `payment_status=partially_paid`. Это подтверждено UI и API. Затем `TestLiveOneCBackendFacts` выполнил отмену: тот же event ID, новая версия, remaining=0, paid=100000, forecast_eligible=false; повтор не создал дубль. После теста GET 1С подтвердил исходные `Posted=false`, `DeletionMark=true`, сумма 350000. Срок на живой базе не придумывался. Входящие/исходящие счета с переносами сроков дополнительно покрыты mock-тестами; промышленная 1С с паролем в эту live-проверку не входила.

### Открытые данные ФНС

Из настоящего Hub прочитан сохранённый официальный снимок `20260925-20181201`, опубликован **25.09.2026**, данные на **01.09.2026**, получен **24.10.2026 08:56:06 UTC**. Новый большой архив в этом этапе не скачивался; предыдущая загрузка описана в `integrations/docs/LIVE_VALIDATION_REPORT.md`. Автоматический scheduler текущего Hub выключен, что отражено в UI. Для сервера нужны настройки INN coverage и расписания. Отсутствие записи не означает отсутствие долга и не даёт баланс ЕНС.

## Проверки

| Проверка | Результат | Доказательство / граница |
|---|---|---|
| Backend `go test ./...` | PASS | PostgreSQL с отдельными случайными схемами, официальный PDF opt-in |
| Backend `go test -race ./...`, `go vet ./...` | PASS | С PostgreSQL; отдельный opt-in live 1С также PASS |
| Integrations `go test ./...`, `go test -race ./...`, `go vet ./...` | PASS | Включая DNS guard, адаптеры, контракты, ограничения парсеров |
| Frontend typecheck | PASS | `tsc --noEmit` |
| ESLint | PASS, 0 ошибок | 4 существующих предупреждения: postcss export, OAuth location navigation, 2 badge vars |
| Unit frontend | PASS, 9 | API session/multipart/concurrency, unknown chart, INN checksum, query filters |
| Frontend production build + API/worker/Hub images | PASS | Собраны и пересозданы контейнеры; SHA сверены |
| P0 browser | PASS | `completion-p0.spec.mjs`: self-service, checksum, чужой tenant, старые фильтры, unknown/zero/measured |
| Регистрация, XLSX и файл 1С | PASS | `file-mapping.spec.mjs`: браузерная регистрация, mapping, копейки/0, repeat; файловый режим без OData, 1 факт и 9000 ₽ из выписки |
| Документы/договор/регулярный платёж/настройки/экспорт/theme | PASS | `finance-crud.spec.mjs`, настоящий ZIP download и reload |
| Живая 1С, auth errors, CSV/forecast/risk/calendar/уведомления/mobile/logout | PASS | 4 теста `platform.spec.mjs`; JS errors и неожиданные HTTP 500 отсутствуют |
| Официальный PDF/профиль | PASS | `registry.spec.mjs`, без банковских операций и присвоения ownership |
| WB/Ozon + Sheets UI/DB/mock | PASS | `marketplaces.spec.mjs` на отдельном sandbox: 4 версии отчётов, 0 bank facts от них, 1 синтетическая банковская операция Sheets, повтор без дублей, ротация key |
| Перезапуск/недоступный worker | PASS | `persistence.spec.mjs` с явным opt-in; queued → done после старта, контрольные количества совпали, сессия сохранилась |
| Backup restore платформы + Hub | PASS | Новые отдельные БД, `pg_restore --exit-on-error --no-owner` |
| Caddy health/ready, config validate и rate isolation | PASS | Локальный HTTP; разные реальные IP контейнеров, 30×401 →429 для A, 401 для B; spoofed XFF не обошёл лимит |
| SMTP/OAuth/публичный HTTPS/нагрузочная приёмка | BLOCKED / NOT_TESTED | Нет production-домена, SMTP/OAuth настроек и профиля нагрузки; DNS не менялся |
| WB/Ozon live, Sheets live, DaData live | NOT_TESTED | Пользователь разрешил оставить подключения без live-проверки продавцов; соответствующих доступов нет |
| UKЭП, OCR, Google OAuth/автопродление, локальный агент 1С | NOT_IMPLEMENTED | Ограничения явно отражены в UI/матрице, не заменены фиктивным успехом |

В общем прогоне были реальные FAIL: скрытые поля мастера 1С и общий rate budget. Они исправлены; неоднозначные тестовые селекторы loading и выбора нескольких найденных счетов уточнены. Неуспешный прогон не объявлялся PASS. Финальные прогоны/скриншоты относятся к указанной ревизии приложения; GitHub Actions здесь не проверялись.

## API, контракты и воспроизведение

Добавлены OpenAPI/generated endpoints: `GET /v1/companies/{companyId}/integration-capabilities`, `POST .../onec/discover`, `GET .../registry`, `POST .../registry/preview`, `POST .../registry/confirm`, `GET .../fns-open-data`, `GET .../marketplace-reports`, `POST /v1/sources/{sourceId}/sheet-preview`, `POST .../sheet-mapping`. Уточнены Source kinds/data_mode, nullable registry-only counterparties, lookup metadata. Исправлены optional-фильтры operations/alerts, unread=false, PATCH источника, `/readyz`, proxy trust и budgets.

Команды из корня, после настройки **локального** env вне Git:

```powershell
$env:GIT_SHA = (git rev-parse HEAD).Trim()
docker compose --env-file <local.env> -p zavozik-full-e2e up -d --build
```

В `backend/` и `integrations/`: `go test ./...`, `go test -race ./...`, `go vet ./...`. `TEST_DATABASE_URL` задаётся вне Git для интеграционных тестов; harness создаёт и удаляет только собственную случайную схему. `LIVE_FNS_PDF` указывает на локальный официальный документ. Live 1С opt-in: `LIVE_ONEC_CONFIG` — файл настроек отдельной копии, `LIVE_ONEC_CANCEL=1` допускается только для специально подготовленного тестового счёта этой копии.

В `underfront/`: `node node_modules/typescript/bin/tsc --noEmit`, `node node_modules/eslint/bin/eslint.js .`, `node node_modules/tsx/dist/cli.mjs --test tests/*.test.ts`, `node node_modules/@playwright/test/cli.js test`. Live/browser opt-in переменные описаны в самих spec-файлах. Restart spec требует `E2E_RESTART_STACK=1` и ограничен именованным локальным стеком; marketplace spec — `E2E_INTEGRATION_SANDBOX=1`, baseURL 3001/API 8081. Mock и restart не направлять на production.

Основные checkpoint-коммиты: `0cf1a89` P0, `b13e246` registry/discovery, `14c7582` marketplaces/Sheets/FNS, `1e53afd` 1С fields/DNS/proxy, `4042d1e` financial UI acceptance, `0049684` credentials, `72e2ada` rate budgets/XLSX, `a7cb248` navigation/recovery/guides. Полный список файлов: `git diff --name-only 2ee5f98..integration`.

## Скриншоты и эксплуатационные ограничения

- [Источники desktop](e2e-v2-screenshots/sources-empty-desktop.png), [mobile](e2e-v2-screenshots/sources-empty-mobile.png).
- [Неизвестный остаток](e2e-v2-screenshots/p0-balance-unknown.png), [настоящий ноль](e2e-v2-screenshots/p0-balance-zero.png), [измеренный остаток](e2e-v2-screenshots/p0-balance-measured.png).
- [PDF ФНС с маской профиля](e2e-v2-screenshots/fns-registry-saved-redacted.png), [живая 1С](e2e-v2-screenshots/onec-live-redacted.png), [живая частичная оплата](e2e-v2-screenshots/onec-partial-obligations.png).
- [WB/Ozon — явно MOCK](e2e-v2-screenshots/marketplace-sandbox-reports.png), [Sheets](e2e-v2-screenshots/sheets-sandbox-import.png), [dark settings](e2e-v2-screenshots/settings-dark-synthetic.png), [mobile calendar](e2e-v2-screenshots/calendar-mobile-synthetic.png).

Полная карта адаптеров: [INTEGRATIONS_UI_MATRIX.md](INTEGRATIONS_UI_MATRIX.md). Пользовательские действия: [INTEGRATIONS_USER_GUIDE.md](INTEGRATIONS_USER_GUIDE.md). Сервер/backup/proxy: [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md).

До публичного запуска остаются операторские настройки: реальные ключи/таблицы, перечень ИНН и scheduler ФНС, промышленная публикация 1С с доступом сервера, SMTP, юридический текст `/privacy`, OAuth при необходимости, реальные DNS/HTTPS и нагрузочная проверка. Не внедрены автоматическое продление Sheets token, универсальное расписание пользовательских source sync, автоматическое расширение ФНС coverage из всех tenant-ов, УКЭП/OCR и локальный агент 1С. Их отсутствие не маскируется зелёными статусами. Публичный deploy в этом задании не выполнялся.

## Чекпоинт подключения остальных источников

- WB/Ozon: добавлены сохранение зашифрованных реквизитов, test/sync, worker, версии финансовых отчётов и пользовательские формы. Отчёты исключены из банковского факта и прогноза. Проверка с PostgreSQL и mock-поставщиками прошла, повтор не создаёт дублей. Пользователь сообщил, что кабинетов продавца пока нет: живые запросы **не проверены**, подключения остаются доступны для последующего ввода ключей продавца.
- Google Sheets: отдельные preview/mapping endpoints и форма с предпросмотром. Проверены tenancy, отсутствующее/неверное сопоставление, повторный импорт и отключение. Синтетический поставщик работает только при явном включении sandbox на loopback-адресах; отдельный Compose использует отдельный volume.
- Снимок открытых данных ФНС: серверный доступ к существующему Hub, фильтрация по ИНН workspace/сохранённых контрагентов, датировка и явное отсутствие банковского факта. Проверка PostgreSQL/mock Hub прошла; без опубликованного снимка статус `no_snapshot`, секреты и посторонние ИНН не возвращаются.
- `go test ./...` backend (с PostgreSQL) и integrations прошли. Frontend: typecheck, 9 unit-тестов, ESLint без ошибок (4 существующих предупреждения). Результаты браузерной приёмки приведены выше.

## CP0: исходное состояние

- Задание: `CODEX_FULL_PLATFORM_COMPLETION_ALL_INTEGRATIONS_V2.md`. Прямое указание пользователя о ветке имеет приоритет: работаем в `integration`, не в предложенной документом `codex/...`.
- Начало: чистая рабочая директория, `main` / `origin/main` = `2ee5f98`. `integration` / `origin/integration` = `880276d`. Fetch выполнен, `integration` обновлена fast-forward до `2ee5f98`. `main` не изменяется.
- Предыдущие интеграционные коммиты, включая `20b094f`, `e6b2173` и проверку frontend, входят в историю рабочей ветки.
- Резервные копии до изменений БД: локальный каталог `%TEMP%/puls-v2-backups-20261024-193037`, `platform.dump` и `hub.dump` в формате pg_dump custom. Volumes сохранены.
- Стек: основной Compose `zavozik-full-e2e`, Hub `zavozik-integrations`. Основная БД не публикует порт; отдельная БД Hub доступна только на loopback:5543. Локальные env не входят в Git.

## Воспроизведение P0

- В пользовательском браузере открыты источники и пункт «Организация → + Добавить компанию». Форма доступна обычному пользователю; требования разрешения администратора в актуальном frontend/backend не обнаружены. Backend создаёт company и owner membership одной транзакцией; совпадение ИНН не добавляет membership в чужую company.
- В существующем профиле действительно сохранён ИНН с неверной контрольной цифрой. Он не исправляется автоматически и не заменяется данными другой компании. В новых/изменяемых реквизитах добавлена валидация контрольной цифры.
- Ноль на форме новой компании — значение **резерва**, а не полученный банковский баланс. Формулировка «неснижаемый остаток» неоднозначна: заменяется на «Защитный резерв» с явным объяснением. Профиль без операций/остатка не должен получать денежный баланс из этого поля.
- Frontend в исходном `2ee5f98` уже исключает пустые фильтры. Старые URL по-прежнему ломают generated binding на API. Добавлена совместимость: одиночное пустое значение отсутствующего optional-фильтра снимается до binding, непустые неверные значения дают понятный HTTP 400.
- Дополнительно найдено: `unread=false` не фильтровал прочитанные записи. Исправлена серверная семантика, в UI добавлен выбор «Прочитанные».

## Выполнение чекпоинтов

- [x] CP1: полная локальная пересборка и сверка контейнеров/БД.
- [x] CP2/2A/B/C: P0, onboarding, balance provenance, мастер 1С.
- [x] CP3: PDF/XML/ZIP UI и реальный официальный PDF; УКЭП не реализована и отмечена.
- [x] CP4: все имеющиеся адаптеры представлены пользовательскими путями и матрицей; live без ключей не заявлен.
- [x] CP5: API/DB и browser сценарии, финансовые инварианты и состояния ошибок, mobile/light/dark.
- [x] CP6: auth/tenancy, proxy trust, DNS/dial guard, encrypted secrets, bounded parsers; внешний production perimeter отдельно.
- [x] CP7: tests/race/vet, frontend, контейнеры, restart и worker recovery.
- [x] CP8: документация deploy и локальное восстановление backup; публичный HTTPS и почта требуют реальных настроек.
- [x] CP9: отчёт, матрица, guides, скриншоты. Рабочая ветка отправляется обычным push без merge/force.
