package product

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
)

// An explicit schedule already contains final payment dates. In terms mode,
// prepayment is due on start_date and the remainder after deferral_days.
func contractSchedule(d Doc) error {
	start, err := day(text(d, "start_date"))
	if err != nil {
		return bad("Укажите start_date для расчёта графика или передайте готовый schedule")
	}
	entries := []any{}
	prepayment, total := money(number(d, "prepayment")), money(number(d, "total"))
	if total <= 0 {
		return bad("Сумма договора должна быть положительной")
	}
	if prepayment > 0 {
		entries = append(entries, map[string]any{"date": start.Format(domain.DateLayout), "amount": prepayment, "status": "expected"})
	}
	if remainder := money(total - prepayment); remainder > 0 {
		entries = append(entries, map[string]any{"date": start.AddDate(0, 0, int(number(d, "deferral_days"))).Format(domain.DateLayout), "amount": remainder, "status": "expected"})
	}
	for i, previous := range docs(d["schedule"]) {
		if text(previous, "status") != "received" {
			continue
		}
		if i >= len(entries) {
			return platform.Fail(409, "settled_installment", "Нельзя удалить оплаченный платёж из графика")
		}
		next := entries[i].(map[string]any)
		if next["date"] != previous["date"] || money(number(next, "amount")) != money(number(previous, "amount")) {
			return platform.Fail(409, "settled_installment", "Нельзя изменить условия оплаченного платежа")
		}
		next["status"] = "received"
	}
	d["schedule"], d["schedule_mode"] = entries, "terms"
	return nil
}
