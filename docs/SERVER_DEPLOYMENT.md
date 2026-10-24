# Запуск на сервере

Проверенный локально вариант: Docker Compose, PostgreSQL 17, API, worker, ML и production-сборка Next.js. `compose.production.yaml` добавляет Caddy с HTTPS. Требуются Linux-сервер с Docker Compose, DNS-имя, направленное на сервер, и доступные порты 80/443. Выпуск публичного сертификата проверяется уже на сервере с этим DNS-именем.

## Настройка

Скопировать репозиторий вместе с `ml/artifacts/` и `ml/reports/metrics/`. В корне создать `.env` из `.env.example`. Задать:

```dotenv
APP_DOMAIN=finance.example.ru
PUBLIC_URL=https://finance.example.ru
FRONTEND_URL=https://finance.example.ru
COOKIE_SECURE=true
POSTGRES_PASSWORD=<случайная строка hex>
JWT_SECRET=<случайная строка минимум 32 байта>
DATA_ENCRYPTION_KEY=<32 случайных байта в base64>
SOURCE_ALLOWED_HOSTS=accounting.example.ru
```

Для генерации значений: `openssl rand -hex 32` для пароля БД и JWT, `openssl rand -base64 32` для ключа шифрования. Файл `.env` хранить с правами `600`; реальные значения в Git не добавлять. `DATA_ENCRYPTION_KEY` должен сохраняться вместе с резервными копиями БД: без него сохранённые подключения не расшифруются.

```bash
docker compose -f compose.yaml -f compose.production.yaml config --quiet
docker compose -f compose.yaml -f compose.production.yaml up -d --build
docker compose -f compose.yaml -f compose.production.yaml ps
curl --fail https://finance.example.ru/healthz
```

Миграции выполняет одноразовый `migrate` до API/worker. Данные PostgreSQL и сертификаты Caddy сохраняются в named volumes. Сервисы автоматически запускаются после рестарта Docker. Не использовать `down -v` на сервере с данными.

Открыть сайт, зарегистрировать тестового пользователя, создать компанию, загрузить тестовую выписку и проверить обзор. Для реального пользователя нужны его выписка и подтверждённый остаток: одних банковских документов OData недостаточно для расчёта остатка.

## Подключение 1С

Пользователь указывает ИНН, HTTPS URL опубликованного стандартного OData, 20-значный счёт и учётную запись с правом чтения. Администратор разрешает точный `host:port` в `SOURCE_ALLOWED_HOSTS`. Публикация должна быть доступна с сервера. Адрес `127.0.0.1` на сервере не ведёт к 1С на компьютере пользователя. Для закрытой сети нужен VPN/защищённый доступ и HTTPS; сертификат должен быть доверенным.

Локальные TCP-прокси из E2E-аудита нужны только учебной 1С на Windows и не входят в production-конфигурацию. Автоматические live-тесты не направлять на рабочую базу 1С.

## Дополнительные сервисы

`DADATA_API_TOKEN`, OAuth и SMTP задаются только при наличии соответствующих учётных данных. Без SMTP доставка восстановления пароля не готова. До публичной регистрации требуется заполнить юридический документ `/privacy`.

Текущий ограничитель авторизации допускает 30 auth-запросов в минуту на непосредственный IP. За общим Next.js proxy этот лимит разделяется пользователями. Обычная навигация SPA не создаёт refresh на каждую страницу; перед массовым публичным запуском нужно отдельно настроить доверенную цепочку proxy и проверить лимиты под ожидаемой нагрузкой. Локальный аудит не является нагрузочной приёмкой.

Пользовательские источники backend используют Go-пакет `integrations/bridge` внутри API/worker. Standalone Hub — отдельный сервис для его собственного API, ФНС-архивов и маркетплейсов; его запуск описан в `integrations/README.md`. Запуск Hub сам по себе не добавляет WB/Ozon и прямую ФНС в пользовательский frontend.

## Обновление и сохранность

Перед обновлением сделать `pg_dump` и сохранить ключ шифрования в защищённом хранилище. Например, из корня проекта:

```bash
docker compose exec -T postgres pg_dump -U zavozik -d zavozik -Fc > zavozik-backup.dump
docker compose -f compose.yaml -f compose.production.yaml up -d --build
docker compose -f compose.yaml -f compose.production.yaml logs --tail=100 api worker frontend proxy
```

Команда запуска сохраняет volume БД. Для отката нужны предыдущий Git-коммит/образы; совместимость отката с уже применёнными миграциями проверяется отдельно. Публичное развёртывание и восстановление резервной копии на удалённом сервере в локальный аудит не входят.
