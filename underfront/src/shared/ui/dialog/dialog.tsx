"use client";

import {
  ReactNode,
  useEffect,
  useId,
  useRef,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import {
  registerDialog,
  currentDialogPanel,
} from "@/src/shared/ui/dialog-stack";
import { cn } from "@/src/shared/lib/cn";

/** Назначение функции: Предоставляет стабильную пустую подписку для перехода SSR snapshot к браузерному.
 * Зачем используется: Portal не читает document на сервере и появляется после hydration без синхронного setState в effect. */
function subscribeMount() {
  return () => {};
}
/** Назначение функции: Подтверждает доступность DOM в браузерном snapshot внешнего хранилища.
 * Зачем используется: React синхронизирует portal с клиентом после серверной разметки. */
function browserMounted() {
  return true;
}
/** Назначение функции: Возвращает отсутствие DOM для серверного рендера диалога.
 * Зачем используется: SSR не создаёт другой HTML и не обращается к document.body. */
function serverMounted() {
  return false;
}

interface DialogProps {
  open: boolean;
  title?: string;
  description?: string;
  onClose: () => void;
  children?: ReactNode;
  className?: string;
  contentClassName?: string;
  dismissDisabled?: boolean;
  headerActions?: ReactNode;
  /** Рабочий редактор может занимать весь viewport, сохраняя обычный модальный стек и удержание фокуса. */
  fullScreen?: boolean;
}

/**
 * Показывает доступный модальный слой с удержанием фокуса; позволяет форме
 * временно запретить закрытие, чтобы незавершённая запись не потеряла черновик.
 * Назначение функции: Отображает доступный модальный диалог и удерживает в нём фокус.
 * Зачем используется: Блокирует закрытие при dismissDisabled без повторной инициализации фокуса и потери черновика.
 */
export function Dialog({
  open,
  title,
  description,
  onClose,
  children,
  className,
  contentClassName,
  dismissDisabled = false,
  headerActions,
  fullScreen = false,
}: DialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const mounted = useSyncExternalStore(
    subscribeMount,
    browserMounted,
    serverMounted
  );

  // Callers pass `onClose` as an inline arrow, so its identity changes on every
  // render of the parent. Keeping it out of the effect's dependencies is what
  // stops the effect from tearing down and re-running on each keystroke: that
  // re-ran the initial-focus frame and interrupted typing in cabinet forms.
  const onCloseRef = useRef(onClose);
  const dismissDisabledRef = useRef(dismissDisabled);
  useEffect(() => {
    onCloseRef.current = onClose;
    dismissDisabledRef.current = dismissDisabled;
  }, [onClose, dismissDisabled]);

  useEffect(() => {
    if (!open || !mounted) return;
    const registration = registerDialog(() => dialogRef.current);
    if (overlayRef.current)
      overlayRef.current.style.zIndex = String(registration.layer);

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusableSelector =
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusFrame = requestAnimationFrame(() => {
      if (!registration.isTop()) return;
      const firstFocusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ??
          []
      ).find(
        (element) =>
          element.dataset.dialogInitialFocus !== "skip" &&
          element.getClientRects().length > 0
      );
      (firstFocusable ?? dialogRef.current)?.focus();
    });

    /**
     * Удерживает клавиатурный фокус в верхнем диалоге и разрешает Escape только
     * после снятия блокировки записи, не перезапуская начальный выбор фокуса.
     * Назначение функции: Обрабатывает Escape и Tab только для верхнего активного диалога.
     * Зачем используется: Не даёт закрыть форму во время записи либо перенести клавиатурный фокус за пределы диалога.
     */
    const handleKeyDown = (event: KeyboardEvent) => {
      // An inner control may already have handled Escape (for example a select menu).
      if (event.defaultPrevented || !registration.isTop()) return;
      if (event.key === "Escape") {
        if (dismissDisabledRef.current) event.preventDefault();
        else onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;

      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(focusableSelector)
      ).filter((element) => element.getClientRects().length > 0);
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      cancelAnimationFrame(focusFrame);
      const wasTop = registration.release();
      window.removeEventListener("keydown", handleKeyDown);
      if (wasTop) {
        if (previouslyFocused?.isConnected) previouslyFocused.focus();
        else currentDialogPanel()?.focus();
      }
    };
  }, [open, mounted]);

  if (!mounted) return null;
  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          className={cn(
            "fixed inset-0 flex items-center justify-center",
            "bg-[var(--overlay)] backdrop-blur-[2px]",
            fullScreen ? "p-0" : "p-3 sm:p-4"
          )}
          ref={overlayRef}
          style={{ zIndex: 9990 }}
          onMouseDown={(event) => {
            event.stopPropagation();
            if (!dismissDisabled) onClose();
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
        >
          <motion.div
            ref={dialogRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-busy={dismissDisabled || undefined}
            aria-labelledby={title ? titleId : undefined}
            aria-describedby={description ? descriptionId : undefined}
            className={cn(
              "flex w-full min-w-0 flex-col overflow-hidden",
              !fullScreen &&
                !/(?:^|\s)max-w-/.test(className ?? "") &&
                "max-w-[448px]",
              fullScreen
                ? "h-dvh max-h-dvh max-w-none rounded-none"
                : "max-h-[calc(100dvh-24px)] rounded-[8px] sm:max-h-[calc(100dvh-32px)]",
              "border border-[color:var(--dialog-border)]",
              "bg-[color:var(--surface)] text-[color:var(--dialog-text)]",
              "text-sm font-normal leading-5 tabular-nums",
              "shadow-[var(--dialog-shadow)]",
              className
            )}
            onMouseDown={(event) => event.stopPropagation()}
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{
              duration: 0.2,
              ease: "easeOut",
            }}
          >
            {(title || description || headerActions) && (
              <div
                className={cn(
                  "flex shrink-0 items-start justify-between gap-4",
                  "bg-[var(--surface)] px-5 pt-4"
                )}
              >
                <div className="min-w-0 space-y-1">
                  {title ? (
                    <h3
                      id={titleId}
                      className="text-sm font-semibold leading-7 text-[color:var(--dialog-text)]"
                    >
                      {title}
                    </h3>
                  ) : null}

                  {description ? (
                    <p
                      id={descriptionId}
                      className="text-sm font-medium leading-5 text-[color:var(--dialog-description)]"
                    >
                      {description}
                    </p>
                  ) : null}
                </div>

                {headerActions ? <div className="flex shrink-0 items-center gap-1">{headerActions}</div> : null}
              </div>
            )}

            <div
              className={cn(
                "min-h-0 min-w-0 flex-1 overflow-y-auto px-5 py-4",
                "scrollbar-thin scrollbar-track-transparent scrollbar-thumb-[var(--input-border)]",
                contentClassName
              )}
            >
              {children}
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body
  );
}
