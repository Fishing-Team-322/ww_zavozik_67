"use client";

import { formatGapDate, type WaterfallStep } from "@/src/entities/cash-gap";
import { formatRub } from "@/src/shared/lib/charts";
import { Button, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import { gapFocus, sourceLabels } from "./styles";

export function CashGapCausesTable({ steps, onOpenEvent }: { steps: readonly WaterfallStep[]; onOpenEvent: (id: string) => void }) {
  return <div className="max-w-full overflow-x-auto [scrollbar-width:thin]">
    <Table unstyled className="w-full min-w-[780px] border-collapse text-left text-[12px] leading-4">
      <caption className="sr-only">События базового прогноза до первого кассового разрыва</caption>
      <TableHeader unstyled className="bg-[color:var(--sidebar-bg)] text-[color:var(--nav-item-text)]"><TableRow unstyled>{["Событие", "Контрагент", "Дата", "Источник данных", "Сумма", "Влияние на остаток"].map((title, index) => <TableHead unstyled key={title} scope="col" className={`border-y border-[color:var(--border)] px-3 py-2 font-medium ${index > 3 ? "text-right" : ""}`}>{title}</TableHead>)}</TableRow></TableHeader>
      <TableBody>{steps.filter((step) => step.event).map((step) => {
        const event = step.event!;
        return <TableRow unstyled key={step.id} onClick={() => onOpenEvent(event.id)} className="cursor-pointer border-b border-[color:var(--border-muted)] last:border-b-0 hover:bg-[color:var(--nav-item-hover-bg)]">
          <TableCell unstyled className="px-3 py-2"><Button type="button" variant="ghost" onClick={(click) => { click.stopPropagation(); onOpenEvent(event.id); }} className={`h-auto! border-0! p-0! whitespace-normal! justify-start! text-inherit! hover:bg-transparent! hover:text-inherit! rounded-[4px]! text-left text-[13px]! font-medium hover:underline ${gapFocus}`}>{event.title}</Button></TableCell>
          <TableCell unstyled className="px-3 py-2 text-[color:var(--nav-item-text)]">{event.counterparty}</TableCell>
          <TableCell unstyled className="whitespace-nowrap px-3 py-2 tabular-nums">{formatGapDate(event.date)}</TableCell>
          <TableCell unstyled className="px-3 py-2 text-[color:var(--nav-item-text)]">{sourceLabels[event.source]}</TableCell>
          <TableCell unstyled className={`whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums ${event.amount > 0 ? "text-[color:var(--accent)]" : ""}`}>{event.amount > 0 ? "+" : ""}{formatRub(event.amount)}</TableCell>
          <TableCell unstyled className="whitespace-nowrap px-3 py-2 text-right tabular-nums"><span className="text-[color:var(--nav-item-text)]">{formatRub(step.before)} → </span><span className={step.after < 0 ? "text-[color:var(--danger)]" : ""}>{formatRub(step.after)}</span></TableCell>
        </TableRow>;
      })}</TableBody>
    </Table>
  </div>;
}
