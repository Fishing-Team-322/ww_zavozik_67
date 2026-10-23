# Фронтенд

Стек — на выбор фронтендера. Контракт с бэкендом — `api/openapi.yaml`:
клиент генерируется из него (например, openapi-typescript / orval).

Пока API не готов, мок-сервер по контракту:

    npx @stoplight/prism-cli mock api/openapi.yaml   # http://127.0.0.1:4010

Состав страниц и приоритеты — docs/ARCHITECTURE.md.
