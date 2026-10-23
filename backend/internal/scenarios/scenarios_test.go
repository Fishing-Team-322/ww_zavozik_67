package scenarios

import (
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func TestScaleRevenueDoesNotTouchBase(t *testing.T) {
	d := time.Date(2025, 3, 1, 0, 0, 0, 0, time.UTC)
	base := forecast.Result{
		OpeningBalance: 100,
		Dates:          []time.Time{d, d.AddDate(0, 0, 1)},
		Stochastic: forecast.StochasticForecast{
			Inflow:  [][]float64{{50, 50}},
			Outflow: [][]float64{{10, 10}},
		},
	}
	if err := base.Recompute(); err != nil {
		t.Fatal(err)
	}
	got, err := Apply(base, []Step{{Kind: "scale_revenue", Factor: 0.8}})
	if err != nil {
		t.Fatal(err)
	}
	if got.Balances[0][1] != 100+2*(40-10) {
		t.Errorf("scenario balance: %v", got.Balances[0])
	}
	if base.Balances[0][1] != 100+2*(50-10) {
		t.Errorf("base mutated: %v", base.Balances[0])
	}
	if _, err := Apply(base, []Step{{Kind: "nope"}}); err == nil {
		t.Error("unknown kind must fail")
	}
}
