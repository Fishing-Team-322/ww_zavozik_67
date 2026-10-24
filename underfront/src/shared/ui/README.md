# Общие UI-компоненты

- `src/shared/ui/<component-name>/` — базовые элементы с локальным `index.ts`.
- `src/shared/ui/index.ts` — общий публичный вход для UI-кита.
- Размеры контролов используют шкалу `sm / md / lg` и общие состояния focus, disabled и invalid.
- Здесь не должно быть импортов из `entities`, `features`, `widgets` или `app`.
