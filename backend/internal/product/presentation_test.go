package product

import (
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func TestGapCountdownUsesCurrentCalendarDayInsteadOfStatementDate(t *testing.T) {
	asOf := time.Date(2026, 9, 29, 0, 0, 0, 0, time.UTC)
	r := forecast.Result{AsOf: asOf, OpeningBalance: 100, Stochastic: forecast.StochasticForecast{Inflow: [][]float64{make([]float64, 30)}, Outflow: [][]float64{make([]float64, 30)}}}
	for i := 0; i < 30; i++ {
		r.Dates = append(r.Dates, asOf.AddDate(0, 0, i+1))
	}
	r.Stochastic.Outflow[0][27] = 200 // First risk: 27 October, 28 days after the statement.
	if err := r.Recompute(); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name string
		now  time.Time
		want int
	}{
		{"two_days_left", time.Date(2026, 10, 25, 0, 0, 0, 0, time.UTC), 2},
		{"late_evening_does_not_round_down", time.Date(2026, 10, 25, 23, 59, 59, 0, time.UTC), 2},
		{"today", time.Date(2026, 10, 27, 15, 0, 0, 0, time.UTC), 0},
		{"past", time.Date(2026, 10, 28, 1, 0, 0, 0, time.UTC), -1},
		{"offset_clock_uses_same_utc_date", time.Date(2026, 10, 26, 1, 0, 0, 0, time.FixedZone("MSK", 3*60*60)), 2},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s := Service{Now: func() time.Time { return tc.now }}
			gaps := s.gapDocuments(r, 0)
			if len(gaps) != 1 || text(gaps[0], "date") != "2026-10-27" || number(gaps[0], "days_left") != float64(tc.want) {
				t.Fatalf("gap countdown: got %v, want %d", gaps, tc.want)
			}
		})
	}
}

func TestGapExplanationDateCanFollowFirstRiskWithoutLosingLaterPayments(t *testing.T) {
	asOf := time.Date(2026, 10, 24, 0, 0, 0, 0, time.UTC)
	r := forecast.Result{AsOf: asOf, OpeningBalance: 100, Dates: []time.Time{asOf.AddDate(0, 0, 1), asOf.AddDate(0, 0, 2), asOf.AddDate(0, 0, 3)}, Stochastic: forecast.StochasticForecast{Inflow: [][]float64{{0, 0, 0}}, Outflow: [][]float64{{110, 0, 0}}}, Deterministic: []forecast.ComponentFlow{{Date: asOf.AddDate(0, 0, 3), Key: "event:later-payment", Title: "Later payment", Amount: -50}}}
	if err := r.Recompute(); err != nil {
		t.Fatal(err)
	}
	s := Service{Now: func() time.Time { return asOf }}
	gap := s.gapDocuments(r, 0)[0]
	if text(gap, "date") != "2026-10-25" || text(gap, "worst_date") != "2026-10-27" {
		t.Fatal("first risk and explanation dates must remain distinct", gap)
	}
	explanation := gap["explanation"].(Doc)
	if text(explanation, "date") != text(gap, "worst_date") {
		t.Fatal("explanation date differs from the displayed worst date", gap)
	}
	var sum float64
	var laterFound bool
	for _, cause := range docs(gap["causes"]) {
		sum += number(cause, "amount")
		laterFound = laterFound || text(cause, "items_ref") == "later-payment"
	}
	if !laterFound || sum != -60 || number(explanation, "balance") != sum {
		t.Fatal("later payments must still explain the displayed worst-day balance", gap)
	}
}
