package product

import (
	"math"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func TestGapExplanationAccountsForModelFlowsAndKnownPayments(t *testing.T) {
	start := time.Date(2026, 10, 23, 0, 0, 0, 0, time.UTC)
	r := forecast.Result{AsOf: start, OpeningBalance: 100, Dates: []time.Time{start.AddDate(0, 0, 1), start.AddDate(0, 0, 2)}, Stochastic: forecast.StochasticForecast{Inflow: [][]float64{{10, 10}, {20, 20}}, Outflow: [][]float64{{70, 80}, {60, 100}}}, Deterministic: []forecast.ComponentFlow{{Date: start.AddDate(0, 0, 2), Key: "event:known-invoice", Title: "Invoice", Amount: domain.Money(-30)}}, Uncertain: []forecast.PathComponent{{Date: start.AddDate(0, 0, 2), Key: "event:known-invoice", Values: []float64{-10, 10}}}}
	if e := r.Recompute(); e != nil {
		t.Fatal(e)
	}
	explanation, causes := explainGap(r, r.Dates[1], 10)
	sum := 0.0
	hasModelIn, hasModelOut, hasInvoice := false, false, false
	for _, cause := range causes {
		sum += number(cause, "amount")
		switch text(cause, "component_key") {
		case "model:inflow":
			hasModelIn = true
		case "model:outflow":
			hasModelOut = true
		case "event:known-invoice":
			hasInvoice = true
		}
	}
	if !hasModelIn || !hasModelOut || !hasInvoice || math.Abs(sum-(number(explanation, "balance")-10)) > .011 || number(explanation, "shortfall") != number(explanation, "reserve")-number(explanation, "balance") {
		t.Fatal("explanation does not balance", explanation, causes)
	}
	// A risk generated entirely by model transactions still has a useful cause.
	r.Deterministic = nil
	r.Uncertain = nil
	r.Recompute()
	explanation, causes = explainGap(r, r.Dates[1], 10)
	if len(causes) < 3 || text(explanation, "summary") == "" || number(explanation, "outflow") <= number(explanation, "inflow") {
		t.Fatal(explanation, causes)
	}
}
