import { simulateCashGap, type CashGapGateway } from "@/src/entities/cash-gap";
import { CASH_GAP_DEMO } from "../model/mock-data";

function pause(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("Отменено", "AbortError")); return; }
    const abort = () => { clearTimeout(timer); reject(new DOMException("Отменено", "AbortError")); };
    const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, 300);
    signal?.addEventListener("abort", abort, { once: true });
  });
}

/** Задержка имитирует жизненный цикл запроса. Сеть и банковские данные не используются. */
export function createMockCashGapService(options: { empty?: boolean; failSimulation?: boolean } = {}): Pick<CashGapGateway, "getGap" | "simulate"> {
  function assertScope(companyId: string, gapId: string) {
    if (companyId !== CASH_GAP_DEMO.scenario.companyId || gapId !== CASH_GAP_DEMO.scenario.id) throw new Error("Демонстрационный сценарий не найден.");
  }
  return {
    async getGap(companyId, gapId, signal) {
      await pause(signal);
      assertScope(companyId, gapId);
      return options.empty ? null : structuredClone(CASH_GAP_DEMO);
    },
    async simulate(companyId, gapId, request, signal) {
      await pause(signal);
      assertScope(companyId, gapId);
      if (options.failSimulation) throw new Error("Демо-ошибка расчёта. Исходные данные сохранены — попробуйте ещё раз.");
      return simulateCashGap(CASH_GAP_DEMO, request.actionIds);
    },
  };
}
