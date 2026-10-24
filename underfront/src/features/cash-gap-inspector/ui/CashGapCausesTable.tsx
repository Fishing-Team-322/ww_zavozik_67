"use client";

import { formatGapDate, type WaterfallStep } from "@/src/entities/cash-gap";
import { formatRub } from "@/src/shared/lib/charts";
import { Button, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import { sourceLabels } from "./styles";

export function CashGapCausesTable({ steps, onOpenEvent }: { steps: readonly WaterfallStep[]; onOpenEvent: (id: string) => void }) {
  return <div className="max-w-full overflow-x-auto [scrollbar-width:thin]">
    <Table density="compact" className="min-w-[780px]">
      <caption className="sr-only">События базового прогноза до первого кассового разрыва</caption>
      <TableHeader><TableRow>{["Событие", "Контрагент", "Дата", "Источник данных", "Сумма", "Влияние на остаток"].map((title, index) => <TableHead key={title} scope="col" numeric={index > 3}>{title}</TableHead>)}</TableRow></TableHeader>
      <TableBody>{steps.filter((step) => step.event).map((step) => {
        const event = step.event!;
        return <TableRow key={step.id} onClick={() => onOpenEvent(event.id)} className="cursor-pointer">
          <TableCell><Button type="button" variant="ghost" title={event.title} onClick={(click) => { click.stopPropagation(); onOpenEvent(event.id); }}><span className="max-w-64 truncate">{event.title}</span></Button></TableCell>
          <TableCell tone="muted">{event.counterparty}</TableCell>
          <TableCell className="whitespace-nowrap">{formatGapDate(event.date)}</TableCell>
          <TableCell tone="muted">{sourceLabels[event.source]}</TableCell>
          <TableCell numeric className="whitespace-nowrap">{event.amount > 0 ? "+" : ""}{formatRub(event.amount)}</TableCell>
          <TableCell numeric className="whitespace-nowrap"><span>{formatRub(step.before)} → </span><span className={step.after < 0 ? "text-[color:var(--danger)]" : ""}>{formatRub(step.after)}</span></TableCell>
        </TableRow>;
      })}</TableBody>
    </Table>
  </div>;
}
