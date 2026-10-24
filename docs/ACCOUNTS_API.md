# Аккаунты, компании и облачное состояние

Реализация на Go в `backend/internal/platform`, HTTP-методы — в
`backend/internal/httpapi/platform.go`, Postgres — `backend/internal/store`.
Контракт: `api/openapi.yaml`; сгенерированные файлы обновляются через `make gen-api`.

## Домен и границы

Контейнер данных называется **компания** (`Company`): ИП или ООО. Пользователь
может иметь несколько компаний. Доступ к компании проверяется через `memberships`
с ролью owner; администратор платформы не получает доступ к чужим компаниям через
эти методы. Роль admin не назначается при регистрации и не принимается из запроса.
Чужой и отсутствующий UUID дают одинаковый ответ 404.

Есть постоянное серверное хранение пользователей, компаний, сессий и состояния
компании. Состояние доступно с любого устройства после входа. Финансовые маршруты,
импорт и worker реализованы: см. [BACKEND_API.md](BACKEND_API.md). Изменение компании
атомарно повышает ревизию данных и ставит пересчёт в очередь. Для сохранения настроек
источников API и worker должны использовать общий DATA_ENCRYPTION_KEY.

## Запуск

1. Скопировать `.env.example` в `.env`, заполнить `JWT_SECRET` случайным значением
   минимум 32 байта и задать пароль Postgres. Реальные значения не коммитить.
2. Для Compose запустить `make up`: сервис migrate выполняет goose-миграции до API.
3. Для запуска без Compose экспортировать `DATABASE_URL`, `JWT_SECRET`, `PUBLIC_URL`,
   `FRONTEND_URL`, `COOKIE_SECURE` и выполнить из backend:

```sh
go run ./cmd/migrate
go run ./cmd/api
```

Отдельным процессом с тем же окружением запустить `go run ./cmd/worker`.
Применяются все три миграции, включая `00003_product.sql`.

Go не загружает `.env` автоматически. Без DATABASE_URL остаются health и публичный
каталог моделей; аккаунты/компании отвечают 503. При заданном DATABASE_URL неверные
настройки, недоступная БД или отсутствующие миграции прерывают старт.

PUBLIC_URL — origin API, FRONTEND_URL — origin фронта, без пути и завершающего `/`.
Вне localhost/loopback обязательны HTTPS и COOKIE_SECURE=true. Для двух локальных
origin из примера допустимо COOKIE_SECURE=false. Фронт и API должны находиться на
одном site, например app.example.ru и api.example.ru: cookies используют SameSite=Lax.
Cross-origin запросы фронта отправляются с `credentials: 'include'`; CORS разрешает
только FRONTEND_URL. Origin другого сайта отклоняется.

Миграция 00002 расширяет существующие users/companies и создаёт auth_sessions,
password_resets, oauth_identities, oauth_flows, company_state. Down-миграция удаляет
новые данные и отключает парольный вход для OAuth-only пользователей; это не
полный способ восстановления данных. Перед откатом нужна резервная копия.

## Авторизация

Все маршруты ниже имеют префикс `/v1`. Успех — описанный в OpenAPI объект либо
массив; ошибки всегда `{ "code": "...", "message": "текст для пользователя" }`.
Существующие ответы не оборачиваются в дополнительное поле data. Даты-время —
RFC3339 UTC, деньги — рубли с точностью до копейки. Пустые списки — `[]`, неизвестные
значения data_as_of и city — `null`. Город не определяется по IP и не выдумывается.

| Метод | Путь | Результат |
|---|---|---|
| POST | /auth/register | email, password, consent_pd:true → 201 Token + refresh-cookie |
| POST | /auth/login | email, password → Token + refresh-cookie |
| POST | /auth/refresh | refresh-cookie → Token и новый refresh-cookie |
| POST | /auth/logout | Bearer → 204, отзыв текущей сессии и очистка cookie |
| GET | /auth/providers | Массив настроенных провайдеров: google/yandex |
| GET | /me | Профиль и компании текущего пользователя |
| PATCH | /me/password | old_password, new_password → 204 и отзыв всех сессий |
| GET | /me/sessions | Активные сессии, current, device, last_seen_at |
| DELETE | /me/sessions/{id} | Отзыв своей сессии; чужая — 404 |
| POST | /auth/password/forgot | email → 204 для существующего и неизвестного адреса |
| POST | /auth/password/reset | token, new_password → 204, отзыв всех сессий |

Пароли: Argon2id, 64 MiB, 3 прохода, случайная соль; минимум 8 символов, максимум
256 байт UTF-8. Email нормализуется trim/lowercase и уникален без учёта регистра.
JWT HS256 живёт 15 минут, содержит sub/sid/role, iss=zavozik, aud=zavozik-api.
Авторизация дополнительно проверяет в БД, что сессия активна; права берутся из БД.
Отзыв и смена пароля прекращают использование уже выданных access-токенов.

Refresh — непрозрачный случайный секрет в HttpOnly-cookie zavozik_refresh с
Path=/v1/auth; в БД хранится SHA-256. При refresh секрет атомарно заменяется:
повторное использование предыдущего даёт 401. Срок сессии — 30 дней от входа,
не продлевается refresh-запросами. Фронт должен выполнять refresh последовательно,
включая координацию вкладок, и повторять исходный запрос после получения JWT.
Access-токен хранить в памяти, не помещать в URL.

Для auth действует ограничение 30 запросов в минуту с IP и максимум 4 одновременно
выполняющихся запроса. Ограничитель локален процессу; для нескольких реплик нужен
общий лимит на ingress. X-Forwarded-For не считается доверенным источником IP.
За reverse proxy при отсутствии настройки на ingress лимит применяется к IP proxy.
last_seen_at обновляется при активности с точностью примерно до минуты.

## Восстановление пароля

Заполнить SMTP_ADDR=host:port, SMTP_FROM, при необходимости SMTP_USER/SMTP_PASSWORD.
Удалённая почта требует STARTTLS с проверкой сертификата. Для локального SMTP
перехватчика допустим SMTP_LOCAL_PLAINTEXT=true; через Compose этот флаг не передаётся.
Без SMTP эндпоинт forgot для любого адреса возвращает 503 mail_unavailable.
При настроенном SMTP ответ 204 не раскрывает наличие пользователя, в том числе
при ошибке доставки. Доставка синхронная, без очереди/повторов; production-очередь
и мониторинг доставки остаются дальнейшей работой.

В письмо попадает фиксированная ссылка FRONTEND_URL/reset-password#token=...,
не построенная из Host запроса. Фронту нужно прочитать fragment, убрать его из URL
и отправить POST /auth/password/reset. Токен живёт 30 минут, хранится в БД хешем,
используется один раз; новый запрос восстановления отменяет предыдущую ссылку.

## Google и Яндекс

Включаются только полными парами GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET и
YANDEX_CLIENT_ID/YANDEX_CLIENT_SECRET. Зарегистрировать callback URL:

```text
PUBLIC_URL/v1/auth/oauth/google/callback
PUBLIC_URL/v1/auth/oauth/yandex/callback
```

Фронт после согласия на обработку данных открывает браузером
`GET /v1/auth/oauth/{provider}/start?consent_pd=true`. API задаёт одноразовый state
с HttpOnly-cookie и PKCE S256; callback проверяет cookie/state, обменивает code на
сервере и получает профиль у провайдера. У Google требуется email_verified=true.
Яндекс предоставляет default_email по праву login:email.

Успех: refresh-cookie и redirect на FRONTEND_URL/auth/callback. Фронт вызывает
POST /auth/refresh с credentials, затем GET /me с полученным Bearer. Токены
провайдера не сохраняются. Ошибки callback — JSON; фронту нужен экран повторного входа.
Email не используется для автоматического объединения аккаунтов: при совпадении
с существующим аккаунтом другого способа входа возвращается 409 account_exists.
Привязка нового провайдера к существующему аккаунту в эту версию не входит.

Протоколы: [Google OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
[Яндекс: code и PKCE](https://yandex.com/dev/id/doc/en/codes/code-url),
[Яндекс: профиль](https://yandex.com/dev/id/doc/en/user-information).
Реальный вход требует выданных провайдерами ключей. Тесты используют локальный
сервер провайдера и не подтверждают настройку реальных OAuth-приложений.

## Компании и синхронизация

| Метод | Путь | Результат |
|---|---|---|
| GET / POST | /companies | Список своих / новая компания, атомарно с owner-membership |
| GET / PATCH | /companies/{id} | Чтение / изменение реквизитов и настроек |
| DELETE | /companies/{id} | confirm_name должен точно совпасть; каскадное удаление |
| GET | /companies/{id}/state | company_id, version, data, updated_at |
| PUT | /companies/{id}/state | expected_version, data → сохранённое состояние |

CompanyCreate: name, legal_form (ООО/ИП), industry; необязательные inn (10/12 цифр),
tax_regime (по умолчанию unknown), reserve (0), default_horizon (30/60/90, по умолчанию 30).
PATCH меняет только переданные поля; `inn:null` очищает ИНН.

Облачное состояние — JSON-объект до 512 KiB для черновиков и состояния приложения.
Оно не заменяет типизированные таблицы операций, источников и прогнозов и не
импортирует такие данные из произвольного JSON. Ответы фактических данных должны
по-прежнему использовать соответствующие модели OpenAPI.

Новое состояние: version=0, data={}. Клиент получает его GET-запросом, затем
передаёт PUT с expected_version из ответа. Успешное сохранение увеличивает версию
на 1. При устаревшей версии — 409 version_conflict: получить свежее состояние и
предложить пользователю объединить изменения. Сохранение целого объекта атомарно;
автоматического слияния и фонового polling/WebSocket в этой реализации нет.

## Проверка

```sh
cd backend
TEST_DATABASE_URL='postgres://.../dedicated_test_db?sslmode=disable' go test -race ./...
go vet ./...
```

Интеграционный тест создаёт отдельную случайную схему, выполняет goose-миграции,
проверяет API и удаляет только эту схему. Без TEST_DATABASE_URL он явно пропускается.
CI поднимает Postgres 17 и задаёт эту переменную, поэтому тест там обязателен.
Покрываются изоляция пользователей, два устройства, сохранность после открытия
нового подключения, конкурентная запись, refresh rotation, отзыв и смена/сброс
пароля, OAuth callback/PKCE/state и проверка ответов по реальному OpenAPI-контракту.
