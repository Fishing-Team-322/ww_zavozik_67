package forecast

import (
	"math"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

func TestAdditionalPlanUncertaintyPersistsAndClones(t *testing.T) {
	d := time.Date(2026, 10, 25, 0, 0, 0, 0, time.UTC)
	r := Result{OpeningBalance: 100, Dates: []time.Time{d, d.AddDate(0, 0, 1)},
		Deterministic: []ComponentFlow{{Date: d, Key: "event:one", Amount: domain.Money(50)}},
		Uncertain:     []PathComponent{{Date: d, Key: "event:one", Values: []float64{-50, 50}}},
		Stochastic:    StochasticForecast{Inflow: [][]float64{{0, 0}, {0, 0}}, Outflow: [][]float64{{0, 0}, {0, 0}}}}
	if e := r.Recompute(); e != nil {
		t.Fatal(e)
	}
	// A 100-ruble event at probability .5 is absent or fully present, never half a payment.
	if r.Balances[0][0] != 100 || r.Balances[1][0] != 200 || r.Balances[0][1] != 100 || r.Balances[1][1] != 200 {
		t.Fatal(r.Balances)
	}
	clone := r.Clone()
	clone.Uncertain[0].Values[0] = 0
	clone.Stochastic.Inflow[0][0] = 99
	if r.Uncertain[0].Values[0] != -50 || r.Stochastic.Inflow[0][0] != 0 {
		t.Fatal("scenario mutated base forecast")
	}
	for _, invalid := range [][]float64{{0}, {math.NaN(), 0}, {0, math.Inf(1)}} {
		clone.Uncertain[0].Values = invalid
		if clone.Recompute() == nil {
			t.Fatalf("accepted invalid paths %v", invalid)
		}
	}
}
