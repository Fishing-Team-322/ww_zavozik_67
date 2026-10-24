import { dateKey } from "@/src/entities/payment";
import type { PaymentDraft } from "@/src/entities/payment";

const monthNumbers: Record<string, number> = {
  января: 0, февраля: 1, марта: 2, апреля: 3, мая: 4, июня: 5,
  июля: 6, августа: 7, сентября: 8, октября: 9, ноября: 10, декабря: 11,
};

/** Демонстрационный разбор двух строгих шаблонов. Не угадывает неоднозначные формулировки. */
export function parseMockPayment(text: string, today: Date): PaymentDraft | null {
  const normalized = text.trim().replace(/\s+/g, " ");
  const incoming = normalized.match(/^(Клиент [а-яёa-z0-9 ."«»-]+?|ООО [а-яёa-z0-9 ."«»-]+?|ИП [а-яёa-z0-9 ."«»-]+?) (?:заплатит|перевед[её]т) ([\d\s]+) (?:рубл(?:ей|я|ь)|₽) (\d{1,2}) ([а-яё]+)(?: (\d{4}))?\.?$/i);
  const outgoing = normalized.match(/^(?:Мы|Компания) (?:оплатим|перечислим|заплатим) (.+?) ([\d\s]+) (?:рубл(?:ей|я|ь)|₽) (\d{1,2}) ([а-яё]+)(?: (\d{4}))?\.?$/i);
  const match = incoming ?? outgoing;
  if (!match) return null;
  const [, counterparty, amountText, dayText, monthText, yearText] = match;
  const month = monthNumbers[monthText.toLowerCase()];
  const amount = Number(amountText.replace(/\s/g, ""));
  const day = Number(dayText);
  if (month === undefined || !Number.isSafeInteger(amount) || amount <= 0 || day < 1 || day > 31) return null;
  let year = yearText ? Number(yearText) : today.getFullYear();
  let date = new Date(year, month, day);
  if (date.getMonth() !== month || date.getDate() !== day) return null;
  if (!yearText && dateKey(date) < dateKey(today)) {
    year += 1;
    date = new Date(year, month, day);
  }
  const direction = incoming ? "income" : "expense";
  return {
    title: incoming ? `Оплата от ${counterparty}` : `Оплата ${counterparty}`,
    counterparty: counterparty.trim(),
    amount,
    date: dateKey(date),
    direction,
    category: incoming ? "Клиенты" : "Прочее",
    probability: incoming ? 80 : undefined,
    status: "expected",
  };
}
