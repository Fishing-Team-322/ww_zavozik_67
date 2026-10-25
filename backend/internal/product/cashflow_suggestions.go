package product

import (
	"fmt"
	"math"
	"sort"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/risk"
)

// Candidates reference real unpaid plans. Statutory payments and financing
// repayments are never offered for automatic postponement.
func cashflowCandidates(cid, snapshot string, gap Doc, base forecast.Result, events []Doc) []Doc {
	first, _ := day(text(gap, "date"))
	end := base.Dates[len(base.Dates)-1]
	ordered := append([]Doc(nil), events...)
	sort.SliceStable(ordered, func(i, j int) bool {
		if number(ordered[i], "amount") != number(ordered[j], "amount") {
			return number(ordered[i], "amount") > number(ordered[j], "amount")
		}
		return text(ordered[i], "id") < text(ordered[j], "id")
	})
	actions := []Doc{}
	counts := map[string]int{}
	for _, event := range ordered {
		dt, included := eventForecastDate(event, base.AsOf)
		if !included || text(event, "status") != "expected" || !in(text(event, "source_kind"), "manual recurring invoice") || number(event, "amount") <= 0 {
			continue
		}
		var kind, title, description, conditions, explanation, draft string
		var target time.Time
		switch text(event, "direction") {
		case "out":
			if dt.After(first) || in(text(event, "category"), "tax salary loan_payment leasing bank_fee enforcement own_transfer owner_loan") {
				continue
			}
			kind, title = "shift_supplier_payment", "Согласовать перенос платежа"
			target = dt.AddDate(0, 0, 14)
			description = "Обсудить с поставщиком отсрочку на 14 дней и обновить ожидаемую дату после согласования."
			conditions = "Требуется согласие поставщика. Штрафы и стоимость отсрочки не оценены."
			explanation = "Отсрочка сохраняет деньги до ближайших поступлений. Обязательство остаётся в плане."
			draft = fmt.Sprintf("Здравствуйте! Можем ли согласовать перенос оплаты по «%s» в размере %.2f ₽ с %s на %s? Просим подтвердить условия и возможную стоимость отсрочки.", text(event, "title"), number(event, "amount"), dt.Format(domain.DateLayout), target.Format(domain.DateLayout))
		case "in":
			if !dt.After(first) || domain.Category(text(event, "category")).IsInternal() || text(event, "category") == "refund" {
				continue
			}
			kind, title = "accelerate_receivable", "Запросить более раннюю оплату"
			target = first
			description = "Попросить клиента оплатить запланированное поступление к дате нехватки денег."
			conditions = "Требуется подтверждение клиента. Вероятность поступления сохраняется; скидка за раннюю оплату не учтена."
			explanation = "Более раннее поступление помогает покрыть платежи до возникновения нехватки денег."
			draft = fmt.Sprintf("Здравствуйте! Сможете ли оплатить «%s» в размере %.2f ₽ к %s вместо %s? Просим подтвердить возможность и условия более ранней оплаты.", text(event, "title"), number(event, "amount"), target.Format(domain.DateLayout), dt.Format(domain.DateLayout))
		default:
			continue
		}
		if counts[kind] >= 4 {
			continue
		}
		counts[kind]++
		beyond := target.After(end)
		if beyond {
			conditions += " Платёж перенесён за горизонт прогноза; после него обязательство сохраняется."
		}
		actions = append(actions, Doc{
			"id": idFor(cid, snapshot+":"+kind+":"+text(event, "id")), "kind": kind, "title": title,
			"description": description, "conditions": conditions, "explanation": explanation, "explanation_source": "rules",
			"cost": float64(0), "cost_known": false, "date": target.Format(domain.DateLayout), "original_date": dt.Format(domain.DateLayout), "amount": event["amount"],
			"steps": []Doc{{"kind": "move_event", "event_id": event["id"], "date": target.Format(domain.DateLayout)}},
			"refs":  Doc{"event_id": event["id"], "document_id": event["document_id"]}, "draft_message": draft, "deferred_beyond_horizon": beyond,
		})
	}
	amount := number(gap, "shortfall_p90")
	if amount <= 0 {
		amount = number(gap, "shortfall")
	}
	actions = append(actions, Doc{
		"id": idFor(cid, snapshot+":overdraft"), "kind": "overdraft", "title": "Запланировать привлечение средств",
		"description": "Проверить возможность дополнительного финансирования к дате нехватки денег.",
		"conditions":  "Источник, стоимость и срок возврата необходимо согласовать. Проценты, комиссии и возврат не включены в расчёт.",
		"explanation": "Дополнительное поступление покрывает нехватку в расчёте, если средства удастся привлечь в срок.", "explanation_source": "rules",
		"cost": float64(0), "cost_known": false, "steps": []Doc{}, "refs": Doc{}, "date": gap["date"], "amount": amount, "draft_message": nil, "deferred_beyond_horizon": false,
	})
	return actions
}

func cashflowEffect(base, changed forecast.Result, reserve float64, reliable bool) Doc {
	minimum := func(r forecast.Result, q float64) float64 {
		low := math.Inf(1)
		for _, amount := range r.Quantile(q) {
			low = math.Min(low, amount)
		}
		return money(low)
	}
	beforeMin, afterMin := minimum(base, .5), minimum(changed, .5)
	before, after := money(math.Max(0, reserve-beforeMin)), money(math.Max(0, reserve-afterMin))
	beforeP90, afterP90 := money(math.Max(0, reserve-minimum(base, .1))), money(math.Max(0, reserve-minimum(changed, .1)))
	gs := risk.FindGaps(changed, domain.Money(reserve))
	prob, originalProb := 0.0, 0.0
	var next any
	if original := risk.FindGaps(base, domain.Money(reserve)); len(original) > 0 {
		originalProb = original[0].Probability
	}
	if len(gs) > 0 {
		prob, next = gs[0].Probability, gs[0].Date.Format(domain.DateLayout)
	}
	return Doc{"closes_gap": len(gs) == 0, "baseline_probability": originalProb, "new_probability": prob, "probability_reliable": reliable,
		"baseline_shortfall": before, "new_shortfall": after, "shortfall_reduction": money(before - after),
		"baseline_shortfall_p90": beforeP90, "new_shortfall_p90": afterP90, "shortfall_p90_reduction": money(beforeP90 - afterP90),
		"baseline_min_balance": beforeMin, "new_min_balance": afterMin, "new_gap_date": next}
}

func rankCashflowActions(actions []Doc) {
	sort.SliceStable(actions, func(i, j int) bool {
		// Unpriced external funding is a fallback, not a free improvement.
		if (text(actions[i], "kind") == "overdraft") != (text(actions[j], "kind") == "overdraft") {
			return text(actions[j], "kind") == "overdraft"
		}
		a, b := actions[i]["effect"].(Doc), actions[j]["effect"].(Doc)
		if number(a, "shortfall_p90_reduction") != number(b, "shortfall_p90_reduction") {
			return number(a, "shortfall_p90_reduction") > number(b, "shortfall_p90_reduction")
		}
		return number(a, "shortfall_reduction") > number(b, "shortfall_reduction")
	})
}

func cashflowProbabilityReliable(out Doc) bool {
	if value, exists := out["probability_reliable"]; exists {
		return value == true
	}
	return !flag(out, "fallback_used") && !flag(out, "low_confidence")
}
