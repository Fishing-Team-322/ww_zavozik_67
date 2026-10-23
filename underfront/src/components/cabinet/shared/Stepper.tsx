import { cn } from "@/src/lib/cn";

export type StepperStep = { key: string; label: string };

type StepperProps = {
  steps: StepperStep[];
  currentKey: string;
  /** When set, the lifecycle diverged (failed/cancelled/disputed). */
  branchLabel?: string | null;
};

/**
 * Horizontal lifecycle stepper — the visual centre of the execution and
 * verification flows. Highlights completed / current / upcoming steps.
 * Shared so the reviewer side can reuse it too.
 */
/**
 * Назначение функции: Показывает пройденные, текущий и будущие этапы известного состояния; отмена, сбой и неизвестный код не выдают весь основной путь за завершённый.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function Stepper({ steps, currentKey, branchLabel }: StepperProps) {
  const currentIndex = steps.findIndex((step) => step.key === currentKey);

  return (
    <div className="space-y-3">
      <ol className="flex flex-wrap items-center gap-y-3">
        {steps.map((step, index) => {
          const done = index < currentIndex;
          const active = index === currentIndex && !branchLabel;
          return (
            <li key={step.key} className="flex items-center">
              <div className="flex flex-col items-center gap-1.5">
                <span
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold transition",
                    done &&
                      "border-[color:var(--success)] bg-[color:var(--success)] text-white",
                    active &&
                      "border-[color:var(--accent)] bg-[color:var(--accent)] text-white",
                    !done &&
                      !active &&
                      "border-[color:var(--border)] bg-[color:var(--surface)] text-[color:var(--text-secondary)]"
                  )}
                >
                  {done ? "✓" : index + 1}
                </span>
                <span
                  className={cn(
                    "max-w-[88px] text-center text-[11px] leading-tight",
                    active
                      ? "font-semibold text-[color:var(--text-primary)]"
                      : "text-[color:var(--text-secondary)]"
                  )}
                >
                  {step.label}
                </span>
              </div>
              {index < steps.length - 1 ? (
                <span
                  className={cn(
                    "mx-1.5 h-px w-8 sm:w-12",
                    index < currentIndex
                      ? "bg-[color:var(--success)]"
                      : "bg-[color:var(--border)]"
                  )}
                />
              ) : null}
            </li>
          );
        })}
      </ol>
      {branchLabel ? (
        <p className="text-sm font-medium text-[color:var(--danger)]">
          Ветка процесса: {branchLabel}
        </p>
      ) : null}
    </div>
  );
}
