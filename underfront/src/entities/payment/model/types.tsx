export type PaymentDirection = "income" | "expense";
export type PaymentStatus = "expected" | "received" | "overdue" | "cancelled";
export type PaymentView = "month" | "timeline";

export interface PaymentEvent {
  id: string;
  title: string;
  counterparty: string;
  amount: number;
  date: string;
  direction: PaymentDirection;
  category: string;
  source: string;
  probability?: number;
  status: PaymentStatus;
  manual: boolean;
}

export type PaymentDraft = Omit<PaymentEvent, "id" | "manual" | "source">;

export interface DailyBalance {
  date: string;
  opening: number;
  income: number;
  expense: number;
  closing: number;
  events: PaymentEvent[];
}

export interface MonthForecast {
  days: DailyBalance[];
  opening: number;
  closing: number;
  income: number;
  expense: number;
  minimum: number;
  shortfallDates: string[];
}

/** Контракт для будущего адаптера calendar/events/parse/forecast API. Демо использует локальное состояние. */
export interface PaymentCalendarGateway {
  getCalendar(companyId: string, month: string): Promise<PaymentEvent[]>;
  createEvent(companyId: string, draft: PaymentDraft): Promise<PaymentEvent>;
  parseEvent(companyId: string, text: string): Promise<PaymentDraft | null>;
  updateEvent(eventId: string, changes: Partial<PaymentDraft>): Promise<PaymentEvent>;
  deleteEvent(eventId: string): Promise<void>;
  previewForecast(companyId: string, month: string, events: PaymentEvent[]): Promise<MonthForecast>;
}
