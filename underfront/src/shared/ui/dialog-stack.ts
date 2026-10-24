interface ActiveDialog {
  id: symbol;
  layer: number;
  panel: () => HTMLElement | null;
}
const dialogs: ActiveDialog[] = [];
let unlockedOverflow: string | null = null;
/** Назначение функции: Регистрирует открытое окно над остальными и удерживает общий scroll lock.
 * Зачем используется: Подтверждение TOTP поверх согласования не ломает focus trap и не возвращает прокрутку страницы до закрытия последнего окна. */
export function registerDialog(panel: () => HTMLElement | null) {
  if (!dialogs.length) {
    unlockedOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  const entry = {
    id: Symbol("dialog"),
    layer: (dialogs.at(-1)?.layer ?? 9988) + 2,
    panel,
  };
  dialogs.push(entry);
  /** Назначение функции: Разрешает Escape/Tab только верхнему открытому диалогу.
   * Зачем используется: Один keyboard event не закрывает родительское окно и не перемещает фокус в скрытый нижний modal. */
  const isTop = () => dialogs.at(-1)?.id === entry.id;
  /** Назначение функции: Снимает конкретное окно независимо от порядка unmount и восстанавливает scroll после последнего.
   * Зачем используется: Закрытие родительской формы при работающем дочернем окне не освобождает body и не оставляет вечную блокировку. */
  const release = () => {
    const index = dialogs.findIndex((dialog) => dialog.id === entry.id);
    if (index < 0) return false;
    const wasTop = isTop();
    dialogs.splice(index, 1);
    if (!dialogs.length) {
      document.body.style.overflow = unlockedOverflow ?? "";
      unlockedOverflow = null;
    }
    return wasTop;
  };
  return { layer: entry.layer, isTop, release };
}
/** Назначение функции: Возвращает панель следующего активного окна после закрытия верхнего.
 * Зачем используется: Если исходная кнопка уже исчезла, фокус остаётся в текущем рабочем диалоге. */
export function currentDialogPanel(): HTMLElement | null {
  return dialogs.at(-1)?.panel() ?? null;
}
