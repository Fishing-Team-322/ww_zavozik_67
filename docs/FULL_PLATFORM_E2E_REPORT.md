# Полный аудит платформы и frontend

Дата: 24 октября 2026. Ветка: `test/full-platform-e2e`. Основа: актуальный на начало аудита `origin/main`, `65d4e8e` (в задании был указан более ранний `62a03f7`). Начальная рабочая директория была чистой. Merge в `main`/`integration` не выполнялся.

## Результат

Основной локальный пользовательский путь работает: вход → компания → источники → импорт → операции → прогноз при известном остатке → ручной платёж → сценарий → разрыв и причины. Настоящая учебная 1С подключена через UI; PostgreSQL содержит импортированные факты и обязательства. Публичное развёртывание на удалённом сервере пока не выполнялось.

| Проверка | Статус | Доказательство / граница проверки |
| --- | --- | --- |
| Полный Docker-стек | PASS | PostgreSQL, API, worker, ML, frontend собраны и запущены |
| Standalone Go Hub | PASS | Отдельный существующий Compose, `8091/healthz` → 200 |
| Миграции | PASS | Версия 4, миграции завершаются до API/worker |
| API ↔ ML | PASS | `/healthz`: `status=ok`, `ml=ok`; реальные gRPC-запросы в логах ML |
| UI ↔ API ↔ PostgreSQL | PASS | Playwright, реальные API/worker/БД |
| Учебная 1С через UI | PASS | 15 операций, 7 счетов, автоматический маппинг |
| Повторный sync | PASS | 0 новых операций, 15 повторов; число счетов остаётся 7 |
| Частичная оплата 350/100/250 тыс. ₽ | PASS | Live OData, API и UI; скриншот обязательств |
| Отмена и история | PASS | Та же запись, версия 1 → 2, оплачено 100 тыс., остаток 0; две версии тестового счёта в БД |
| Счета без срока | PASS | Отдельно в источниках, отсутствуют в дневном календаре |
| Прогноз из одной OData-выписки без остатка | BLOCKED | Нет подтверждённого остатка; UI объясняет требование, суммы не выдумываются |
| Синтетическая CSV с остатками | PASS | 240 операций за 120 дней; dashboard, 60-дневный прогноз, событие, сценарий, риск |
| Desktop / mobile | PASS | Проверены рабочие страницы на desktop и 375×812, включая календарь с прокруткой таблицы внутри карточки |
| Авторизация и изоляция | PASS | Гость → 401, чужая компания → 403/404, сессия после reload и restart |
| Публичный HTTPS на сервере | BLOCKED | Нужны сервер и DNS; Compose/Caddy конфигурации валидны локально |
| GitHub CI | BLOCKED | В этом аудите не запускался и не подтверждался; ниже перечислены локальные проверки |

## Запущенная среда

Основной проект Docker: `zavozik-full-e2e`, отдельный volume `zavozik-full-e2e_pgdata`. Новые аккаунты используют адреса `example.invalid`. Существующая БД Hub и пользовательские данные не удалялись.

| Сервис | Доступ | Результат |
| --- | --- | --- |
| Frontend, production Next.js | `http://localhost:3000` | HTTP 200, живой браузер |
| Go API | `http://localhost:8080` | Health 200, ML ok |
| Worker | В сети Compose | Импорт, sync, пересчёты выполняются |
| PostgreSQL 17 | Только сеть основного Compose | Health healthy, SQL-сверка фактов и версий |
| ML | `ml:50051` внутри сети | Артефакты загружены, Forecast отвечает |
| Go Hub | `http://127.0.0.1:8091` | Health 200, список providers доступен |
| Учебная 1С | `127.0.0.1:8093/codexobligations` | OData metadata и документы доступны |

Backend использует общий Go-пакет `integrations/bridge` внутри API/worker. Standalone Hub имеет собственное API и БД; текущий frontend не вызывает его HTTP API. Доступность Hub не означает наличие пользовательских экранов всех его провайдеров.

Для локальной Windows-публикации добавлены временные контейнеры `zavozik-e2e-onec-proxy` и `zavozik-e2e-onec-worker-proxy`: loopback соответствующего сервиса → `host.docker.internal:8093`. Обычный HTTP в OData-клиенте по-прежнему ограничен loopback, точный адрес разрешён администратором. Эти прокси не входят в production Compose и после пересоздания API/worker должны быть привязаны к их новым сетевым пространствам.

`localhost:3000` — настроенный frontend origin. Открытие того же приложения через `127.0.0.1:3000` при таком окружении корректно отвергает изменяющие запросы с другим Origin.

## Проверенные страницы и действия

| Маршруты | Проверено |
| --- | --- |
| `/`, `/overview` | Редирект корня, загрузка dashboard, пустое состояние без остатка, показатели, история и диапазон p10–p90, запрос 60 дней |
| `/transactions` | Реальные операции 1С и CSV, знаки/копейки, итоговые суммы; новые даты первыми; стабильная пагинация проверена unit-тестом |
| `/forecast` | Загрузка, причина отсутствия остатка, 30/60 дней, реальный ответ из 60 точек, предупреждение об ограничениях модели |
| `/scenarios` | Изменение расхода, запрос preview, сохранение сценария через API |
| `/risks` | Риск от синтетического платежа 200 тыс. ₽, дата/сумма, открытие причин и списка действий |
| `/calendar` | Отсутствие недатированных счетов, создание ручного платежа, сохранение после reload |
| `/sources` | 1С: создание, test, sync, повторный sync, ошибочный адрес, статусы, время обновления, счета; CSV: файл, задание, отчёт; DaData: отсутствие ключа |
| `/companies/new` | Создание компании, ручные реквизиты при недоступном lookup |
| `/login`, `/register` | Рабочая форма входа, состояния регистрации; тестовые аккаунты создавались через API, затем входили через UI |
| `/forgot-password`, `/reset-password` | Форма восстановления, явная ошибка ссылки без токена; доставка писем не проверена без SMTP |
| `/auth/callback` | Явное неуспешное состояние при отсутствии сессии |
| `/privacy` | Страница открывается, но содержит сообщение об отсутствующем юридическом документе |
| `/test`, `/development/components` | Демонстрации открыты в браузере; их синтетические данные не использовались для финансовой приёмки |

Рабочие ссылки основного меню ведут на существующие маршруты. Динамические финансовые ответы получены из backend. Страницы разработчика не заменяют реальные пользовательские экраны. На live-сценарии нет необработанных JS-ошибок; на финансовом синтетическом сценарии проверено отсутствие HTTP 500. Быстрый перебор полных перезагрузок достигал штатного auth rate limit 30/min; тест переведён на обычную SPA-навигацию.

## Живая 1С и финансовая сверка

Использована только отдельная учебная `AccountingObligationsE2E`. Исходная опубликованная `codexaccounting` не изменялась.

1. Через UI созданы компания и источник с ИНН, OData URL и счётом. Backend сам определил ключи организации, счетов, валюты и коллекции.
2. Проверка соединения прошла, worker импортировал 15 фактических операций и 7 счетов. Повторный импорт: 0 новых, 15 повторов. SQL подтвердил количество записей.
3. Ранее созданный тестовый счёт был временно восстановлен в этой копии: 350 000 ₽ всего, 100 000 ₽ фактической оплаты, 250 000 ₽ остатка. UI и API совпали. Дополнительный факт на ту же оплату не создавался.
4. `TestLiveOneCBackendFacts` с явным `LIVE_ONEC_CANCEL=1` отменил только этот тестовый документ и проверил обновление на месте и историю. Затем повторный sync через UI обновил сохранённую компанию: тот же ID, версия 2, оплачено 100 000 ₽, остаток 0.
5. В БД компании lifecycle-проверки: 15 операций, 7 текущих обязательств, 8 записей истории (7 первых версий + вторая версия тестового счёта). Последующие smoke-прогоны создают другие компании. Отменённый счёт не участвует в прогнозе.
6. Итоговое состояние тестового документа возвращено к исходному: `Posted=false`, `DeletionMark=true`, подтверждено повторным GET OData.

Все 7 счетов не имеют подтверждённого срока. Оставшееся обычное открытое обязательство — 25 000 ₽; оно видно в источниках и не подставлено в календарь по дате документа. Один старый демонстрационный счёт имеет оплату выше суммы и помечен «Требует сверки». Назначение срока через UI отсутствует (`NOT_IMPLEMENTED`), фиктивная дата не добавлялась.

Документы учебной базы содержат преимущественно даты 2015 года и отдельную тестовую оплату 2026 года, но не подтверждённые закрывающие остатки. Поэтому полноценный прогноз отдельно проверялся на явно синтетической CSV с остатками. ML доступен; на истории с ежедневной активностью выбирает `seasonal_naive` по правилу выхода за область обучения (`out_of_domain_naive_fallback`). UI теперь объясняет именно эту причину.

Учебная платформа иногда отвечает ограничением количества подключений к ИБ после серии проверок. После освобождения сессий OData снова отвечает. Это ограничение учебной 1С, а не разрешение обходить её лицензионные ограничения.

## Другие источники

| Источник | UI / backend | Режим и итог |
| --- | --- | --- |
| CSV/XLSX/1C bank file | Загрузка и importer | PASS: CSV через браузер; XLSX и обе кодировки банковского файла — API-тесты |
| Ручные события | Календарь + CRUD API | PASS: создание, reload, влияние на прогноз и риск |
| DaData | Форма источника и lookup по ИНН | MOCK_READY: успешный ответ, ошибка и восстановление статуса проверены фикстурой; live BLOCKED без токена |
| Прямая ФНС | Hub: архивы/реестр; отдельного пользовательского экрана нет | Backend-фикстуры PASS; UI NOT_IMPLEMENTED. Результаты прежних загрузок ФНС не объявляются новой live-проверкой |
| Google Sheets | Форма ID/диапазона/ключа, test/sync | MOCK_READY: запрос к Sheets API, импорт, повтор без дублей, 403 провайдера и статус ошибки проверены; live BLOCKED без доступа |
| Wildberries | Адаптер Hub | MOCK_READY, provider tests PASS; пользовательский UI и подключение к текущему финансовому backend NOT_IMPLEMENTED |
| Ozon | Адаптер Hub | MOCK_READY, provider tests PASS; пользовательский UI и подключение к текущему финансовому backend NOT_IMPLEMENTED |

Экран backend-источника `kind=fns` фактически использует DaData. Название UI исправлено на «DaData · сведения об организации»; прямой ФНС он не притворяется. У подключений показаны проверка, повторный sync, ошибка и последняя синхронизация. Полный экран редактирования сохранённых настроек подключения пока отсутствует (`NOT_IMPLEMENTED`).

## Исправленные ошибки

- Завершение job прерывало обработку результата во frontend: CSV импортировался, но не появлялся отчёт и не обновлялась компания. Завершение теперь публикуется после загрузки результата; счета также обновляются.
- Ошибка polling оставляла задание без понятного продолжения. Теперь отображается приостановка и кнопка повторной проверки; серверное задание не объявляется ошибочным без основания.
- Список операций был отсортирован по ID. Добавлены дата по убыванию, стабильный ключ при равных датах и курсор пагинации.
- Обзор терял историю, p10/p90, резерв и серверную безопасную сумму. Поля передаются, неизвестные остатки сохраняются как null, разрывы истории не соединяются.
- Табам 60/90 дней раньше соответствовал только локальный срез 30-дневного ответа. Теперь запрашивается соответствующий горизонт backend; добавлена исходная точка остатка на `as_of`.
- Отсутствие остатка ошибочно описывалось как отсутствие операций. Исправлены пустое состояние и показ загрузки/ошибки.
- Выбор резервной модели из-за характера данных выдавался за недоступность ML. Причины различаются по предупреждениям API.
- Проверка DaData/Sheets не сохраняла реальный статус. Ошибка теперь сохраняется, успешная повторная проверка очищает её; UI обновляет карточку.
- Сохранение настроек больше не выдаётся за проверенное соединение. Статусы источников/оплаты переведены, у счетов показаны полная сумма и направление.
- Состояние формы источников теперь привязано к компании через remount: настройки и результат предыдущей компании не переходят в новую форму.
- Отменённые клиентом запросы не регистрируются как внутренние HTTP 500; используются 499/504 для отмены/тайм-аута.
- Исправлены ошибки React/Next lint в текущих компонентах; тестовые traces исключены из Git и Docker build context.
- Исправлено горизонтальное переполнение мобильного календаря: ограничена ширина grid-карточки, заголовок переносится, таблица прокручивается внутри. Такое же ограничение применено к сеткам прогноза и сценариев.
- Добавлены restart policies, production Compose с Caddy и инструкция переноса на сервер.

## Автоматические проверки

| Проверка | Результат |
| --- | --- |
| `backend: go test ./...` | PASS, с TEST_DATABASE_URL и отдельными схемами |
| `backend: go test -race ./...` | PASS |
| `backend: go vet ./...` | PASS |
| `integrations: go test ./...` | PASS |
| `integrations: go test -race ./...` | PASS |
| `integrations: go vet ./...` | PASS |
| Регрессии Sheets/DaData, `TestProductSourceAdaptersAndRecovery -race` | PASS |
| `TestOneCObligationsBackendE2E` | PASS: фикстура 350/100/250, повтор, отказ провайдера, отмена, три версии |
| `TestLiveOneCBackendFacts`, autoconfig + cancellation | PASS: настоящая учебная 1С |
| TypeScript | PASS; старые `.next/types` после обновления main пересозданы сборкой |
| Frontend unit tests | PASS, 7 тестов |
| Полный ESLint | PASS по exit code, 0 ошибок, 4 предупреждения в существующих PostCSS/OAuth/Badge |
| Production build | PASS локально и в Docker |
| Playwright | PASS, 4 теста, включая live smoke и проверку всех финансовых страниц на mobile |
| Compose production / Hub config | PASS |
| Caddy validate | PASS; выпуск публичного сертификата требует реального DNS |
| Перезапуск | PASS: PostgreSQL, ML, API, worker, frontend; health восстановился, сессия сохранилась |

После restart совпали все контрольные количества изолированной БД: 23 пользователя, 17 компаний, 1065 операций, 52 события, 50 версий 1С. Это суммарные записи нескольких запусков тестов, а не результат одной компании и не пользовательская база.

Playwright находится в `underfront/tests/e2e/platform.spec.mjs`. Он проверяет auth-маршруты, отсутствие доступа гостя/чужой компании, неразрешённый OData host, недоступный backend, reload, mobile, live 1С, повторный sync, счета без даты, CSV, сбой и повтор polling, dashboard/forecast, событие, сценарий и риск. Live smoke включается окружением; мутаций 1С он не выполняет. `LIVE_ONEC_EXPECT_PARTIAL=1` дополнительно проверяет активный учебный счёт, если он подготовлен оператором. Прогон с отменой выполнялся отдельным существующим Go-тестом с явным opt-in.

## Скриншоты

Скриншоты просмотрены. Реквизиты формы замаскированы; финансовые примеры — только учебная база или синтетическая компания.

- [Пустые источники, desktop](e2e-screenshots/sources-empty-desktop.png)
- [Источники, mobile](e2e-screenshots/sources-empty-mobile.png)
- [Живое подключение 1С](e2e-screenshots/onec-live-redacted.png)
- [Живая частичная оплата](e2e-screenshots/onec-partial-obligations.png)
- [Тот же счёт после отмены](e2e-screenshots/onec-cancelled-obligations.png)
- [Обзор без подтверждённого остатка](e2e-screenshots/overview-missing-balance.png)
- [Обзор на синтетической CSV](e2e-screenshots/dashboard-synthetic.png)
- [Риск от синтетического платежа](e2e-screenshots/risk-synthetic.png)
- [Мобильный календарь на синтетических данных](e2e-screenshots/calendar-mobile-synthetic.png)

## Перед сервером и демонстрацией

Для демонстрации основной путь готов локально. Использовать [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md): DNS, HTTPS, постоянные volumes, сохранённый ключ шифрования и резервная копия БД. Доступ к пользовательской 1С должен быть организован с сервера; её localhost не переносится вместе с сайтом.

Для публичной регистрации заполнить `/privacy`, настроить SMTP и проверить доставку/сброс пароля. OAuth и внешние провайдеры требуют собственных ключей. Перед массовым запуском требуется настройка доверенной proxy-цепочки для auth rate limit и нагрузочная проверка: текущий лимит разделяется клиентами Next proxy. В данном аудите не выполнены внешний HTTPS, удалённое восстановление backup, нагрузочный тест и live-подключения маркетплейсов/Sheets/DaData.

Функции назначения сроков 1С, UI WB/Ozon/прямой ФНС и полный редактор сохранённых подключений остаются отдельными задачами. ML-код и обученные артефакты не менялись.

## Git

Commit кода: `524a5a8a5f4fe846746fa2940841bfb9a7422abd`. Финальный прогон Playwright: 4 passed (21.1s). Ветки `main` и `integration` не изменены этим аудитом; push/merge не выполнялись.

### Файлы commit кода

- `README.md`
- `backend/internal/httpapi/platform.go`
- `backend/internal/httpapi/product_sources_test.go`
- `backend/internal/httpapi/server.go`
- `backend/internal/httpapi/server_test.go`
- `backend/internal/product/operations.go`
- `backend/internal/product/operations_page_test.go`
- `backend/internal/product/sources.go`
- `compose.production.yaml`
- `compose.yaml`
- `docs/SERVER_DEPLOYMENT.md`
- `docs/e2e-screenshots/calendar-mobile-synthetic.png`
- `docs/e2e-screenshots/dashboard-synthetic.png`
- `docs/e2e-screenshots/onec-cancelled-obligations.png`
- `docs/e2e-screenshots/onec-live-redacted.png`
- `docs/e2e-screenshots/onec-partial-obligations.png`
- `docs/e2e-screenshots/overview-missing-balance.png`
- `docs/e2e-screenshots/risk-synthetic.png`
- `docs/e2e-screenshots/sources-empty-desktop.png`
- `docs/e2e-screenshots/sources-empty-mobile.png`
- `infra/Caddyfile`
- `integrations/compose.yaml`
- `underfront/.dockerignore`
- `underfront/.gitignore`
- `underfront/README.md`
- `underfront/app/[section]/_ui/CalendarScreen.tsx`
- `underfront/app/[section]/_ui/FinanceState.tsx`
- `underfront/app/[section]/_ui/ForecastScreen.tsx`
- `underfront/app/[section]/_ui/ScenariosScreen.tsx`
- `underfront/package-lock.json`
- `underfront/package.json`
- `underfront/playwright.config.mjs`
- `underfront/src/entities/forecast/index.ts`
- `underfront/src/entities/forecast/model/api-adapters.ts`
- `underfront/src/features/auth/model/AuthProvider.tsx`
- `underfront/src/features/cash-gap-inspector/ui/CashGapInspectorDemo.tsx`
- `underfront/src/features/company-context/CompanyProvider.tsx`
- `underfront/src/features/company-create/NewCompanyForm.tsx`
- `underfront/src/features/payment-calendar/ui/PaymentEventPanel.tsx`
- `underfront/src/features/payment-calendar/ui/PaymentTimeline.tsx`
- `underfront/src/features/sources/OneCConnection.tsx`
- `underfront/src/features/sources/SourcesWorkspace.tsx`
- `underfront/src/shared/api/use-api-resource.ts`
- `underfront/src/shared/ui/charts/bar-chart/bar-chart.tsx`
- `underfront/src/widgets/cabinet-shell/ui/SidebarShell.tsx`
- `underfront/src/widgets/puls-overview/ui/PulsOverview.tsx`
- `underfront/src/widgets/puls-overview/ui/PulsOverviewHome.tsx`
- `underfront/tests/e2e/platform.spec.mjs`
- `underfront/tests/forecast-adapters.test.ts`
