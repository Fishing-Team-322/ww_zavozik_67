"use client";

import { formatMoney, parseDate } from "@/src/entities/payment";
import type { DailyBalance, PaymentEvent } from "@/src/entities/payment";

const weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

interface PaymentMonthGridProps {
  days: Array<Pick<DailyBalance, "date" | "events"> & { closing: number | null; risk?: string }>;
  selectedDate: string;
  today: string;
  onSelectDate: (date: string) => void;
  onOpenEvent: (id: string) => void;
  onMoveEvent: (id: string, date: string) => void;
}

function markerColor(event: PaymentEvent): string {
  if (event.direction === "expense") return "bg-[color:var(--nav-item-icon)]";
  if (event.status === "overdue" || (event.probability !== undefined && event.probability < 70)) return "bg-[color:var(--warning)]";
  return "bg-[color:var(--accent)]";
}

export function PaymentMonthGrid({ days, selectedDate, today, onSelectDate, onMoveEvent }: PaymentMonthGridProps) {
  if (!days.length) return <p>Дни календаря пока не загружены.</p>;
  const offset = (parseDate(days[0].date).getDay() + 6) % 7;
  const cells: Array<(typeof days)[number] | null> = [...Array(offset).fill(null), ...days];
  while (cells.length % 7) cells.push(null);

  return (
    <div className="w-full min-w-0" aria-label="Месячный календарь платежей">
      <div className="grid grid-cols-7 pb-2">
        {weekdays.map((weekday, index) => <span key={weekday} className={`text-center text-[12px] font-medium leading-5 ${index > 4 ? "text-[color:var(--text-muted)]" : "text-[color:var(--nav-item-text)]"}`}>{weekday}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((day, index) => {
          if (!day) return <span key={`empty-${index}`} aria-hidden="true" className="h-11" />;
          const activeEvents = day.events.filter((event) => event.status !== "cancelled");
          const markers = [...new Set(activeEvents.map(markerColor))];
          const selected = day.date === selectedDate;
          const weekend = index % 7 > 4;
          const risk = day.risk === "danger" || day.risk === "warning" || (day.closing !== null && day.closing < 0);
          return <button
            key={day.date}
            type="button"
            onClick={() => onSelectDate(day.date)}
            onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }}
            onDrop={(event) => { event.preventDefault(); const id = event.dataTransfer.getData("text/plain"); if (id) onMoveEvent(id, day.date); }}
            aria-label={`${parseDate(day.date).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}, остаток ${(day.closing === null ? "нет оценки" : formatMoney(day.closing))}, событий ${activeEvents.length}${risk ? ", возможная нехватка денег" : ""}`}
            aria-pressed={selected}
            title="Нажмите для выбора дня или перенесите сюда событие"
            className={`relative flex h-11 min-w-0 flex-col items-center justify-center gap-1 rounded-[5px] transition-colors ${selected ? "bg-[color:var(--nav-item-active-bg)] ring-1 ring-inset ring-[color:var(--nav-item-active-border)]" : "hover:bg-[color:var(--nav-item-hover-bg)]"} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--nav-focus-ring)]`}
          >
            <span className={`flex size-5 items-center justify-center rounded-[4px] text-[13px] leading-5 tabular-nums ${activeEvents.length ? "font-semibold" : "font-medium"} ${day.date === today ? "bg-[color:var(--nav-item-active-text)] text-[color:var(--surface)]" : weekend ? "text-[color:var(--nav-item-text)]" : "text-[color:var(--nav-item-active-text)]"}`}>{parseDate(day.date).getDate()}</span>
            <span aria-hidden="true" className="flex h-1.5 items-center justify-center gap-1">
              {markers.slice(0, risk ? 1 : 2).map((color) => <span key={color} className={`size-1.5 rounded-full ${color}`} />)}
            </span>
            {risk ? <span aria-hidden="true" className="absolute right-1 top-1 size-1.5 rounded-full bg-[color:var(--danger)]" /> : null}
          </button>;
        })}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-[color:var(--border-muted)] pt-2 text-[12px] leading-4 text-[color:var(--nav-item-text)]">
        <span className="inline-flex items-center gap-1"><i className="size-1.5 rounded-full bg-[color:var(--accent)]" />Поступление</span>
        <span className="inline-flex items-center gap-1"><i className="size-1.5 rounded-full bg-[color:var(--nav-item-icon)]" />Списание</span>
        <span className="inline-flex items-center gap-1" title="Поступление с низкой вероятностью или просрочкой"><i className="size-1.5 rounded-full bg-[color:var(--warning)]" />Под вопросом</span>
        <span className="inline-flex items-center gap-1"><i className="size-1.5 rounded-full bg-[color:var(--danger)]" />Риск</span>
      </div>
    </div>
  );
}
