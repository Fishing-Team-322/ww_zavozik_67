package product

import (
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

// Explain a median balance with the same interpolation of paths as Quantile(.5).
// Opening balance + model flows + explicit events - reserve sum to the displayed
// balance relative to reserve. Model-generated flows are labeled as predictions,
// not asserted to be identified invoices or actual transaction-level causes.
func explainGap(r forecast.Result, first time.Time, reserve float64) (Doc, []Doc) {
	start := r.DayIndex(first)
	if start < 0 || len(r.Balances) == 0 {
		return Doc{}, []Doc{}
	}
	median := r.Quantile(.5)
	worst := start
	for i := start; i < len(median); i++ {
		if median[i] < median[worst] {
			worst = i
		}
	}
	order := make([]int, len(r.Balances))
	for i := range order {
		order[i] = i
	}
	sort.SliceStable(order, func(i, j int) bool { return r.Balances[order[i]][worst] < r.Balances[order[j]][worst] })
	left, right := order[(len(order)-1)/2], order[len(order)/2]
	modelIn, modelOut := 0.0, 0.0
	for i := 0; i <= worst; i++ {
		modelIn += (r.Stochastic.Inflow[left][i] + r.Stochastic.Inflow[right][i]) / 2
		modelOut += (r.Stochastic.Outflow[left][i] + r.Stochastic.Outflow[right][i]) / 2
	}
	causes := []Doc{{"title": "Деньги на начало прогноза", "amount": money(r.OpeningBalance.Float()), "component_key": "opening_balance", "items_ref": nil},
		{"title": "Прогноз поступлений по модели", "amount": money(modelIn), "component_key": "model:inflow", "items_ref": nil},
		{"title": "Прогноз расходов по модели", "amount": -money(modelOut), "component_key": "model:outflow", "items_ref": nil}}
	components := map[string]Doc{}
	keys := []string{}
	for _, c := range r.Deterministic {
		if day := r.DayIndex(c.Date); day < 0 || day > worst {
			continue
		}
		if components[c.Key] == nil {
			var ref any
			if strings.HasPrefix(c.Key, "event:") {
				ref = strings.TrimPrefix(c.Key, "event:")
			}
			components[c.Key] = Doc{"title": c.Title, "amount": 0.0, "component_key": c.Key, "items_ref": ref}
			keys = append(keys, c.Key)
		}
		components[c.Key]["amount"] = number(components[c.Key], "amount") + c.Amount.Float()
	}
	for _, c := range r.Uncertain {
		if day := r.DayIndex(c.Date); day < 0 || day > worst {
			continue
		}
		if component := components[c.Key]; component != nil {
			component["amount"] = number(component, "amount") + (c.Values[left]+c.Values[right])/2
		}
	}
	inflow, outflow := modelIn, modelOut
	for _, key := range keys {
		component := components[key]
		amount := number(component, "amount")
		if amount >= 0 {
			inflow += amount
		} else {
			outflow -= amount
		}
		component["amount"] = money(amount)
		causes = append(causes, component)
	}
	causes = append(causes, Doc{"title": "Неснижаемый резерв", "amount": -money(reserve), "component_key": "reserve", "items_ref": nil})
	date := r.Dates[worst].Format("2006-01-02")
	shortfall := math.Max(0, reserve-median[worst])
	below := 0
	for _, path := range r.Balances {
		if path[start] < reserve {
			below++
		}
	}
	summary := fmt.Sprintf("К %s ожидаются поступления %.2f ₽ и расходы %.2f ₽ при начальном остатке %.2f ₽ и резерве %.2f ₽.", date, money(inflow), money(outflow), money(r.OpeningBalance.Float()), money(reserve))
	if shortfall > 0 {
		summary += fmt.Sprintf(" По медианному прогнозу не хватает %.2f ₽.", money(shortfall))
	} else {
		summary += " В медианном прогнозе средств хватает, но часть возможных траекторий опускается ниже резерва."
	}
	return Doc{"date": date, "opening_balance": money(r.OpeningBalance.Float()), "inflow": money(inflow), "outflow": money(outflow), "balance": money(median[worst]), "reserve": money(reserve), "shortfall": money(shortfall), "probability_on_first_date": float64(below) / float64(len(r.Balances)), "basis": "median_balance_paths", "summary": summary}, causes
}
