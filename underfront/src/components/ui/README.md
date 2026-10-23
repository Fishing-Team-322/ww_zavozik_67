# UI: primitives vs composed components

- `src/components/ui/<component-name>/` — каждый UI-компонент хранится в своей папке с реализацией, barrel-экспортом и stories.
- `src/components/ui/index.ts` — общий barrel для импорта из `@/src/components/ui`.
- Для форм используйте импорты из `@/src/components/ui/<component-name>` или `@/src/components/ui`, если не нужна локальная низкоуровневая кастомизация.
- Размеры и состояния базовых контролов синхронизированы через шкалу `sm / md / lg` и общие state-стили (focus/disabled/invalid).
