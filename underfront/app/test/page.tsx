import type { Metadata } from "next";
import { PaymentCalendarDemo } from "@/src/features/payment-calendar";
import { CashGapInspectorDemo } from "@/src/features/cash-gap-inspector";

export const metadata: Metadata = { title: "Платёжный календарь — ПУЛЬС" };

export default function TestPage() {
  return (
    <div className="min-w-0 space-y-8">
      <PaymentCalendarDemo />
      <CashGapInspectorDemo />
    </div>
  );
}
