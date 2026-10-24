package forecast_test

import (
	"encoding/json"
	"math"
	"os"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/risk"
)

// Shared fixtures pin the same alarm semantics in ML evaluation and Go.
func TestMLRiskContract(t *testing.T) {
	data, err := os.ReadFile("../../../ml/tests/fixtures/risk_contract.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name        string      `json:"name"`
		Paths       [][]float64 `json:"paths"`
		DateIndex   *int        `json:"date_index"`
		Shortfall   float64     `json:"shortfall"`
		Probability float64     `json:"probability"`
	}
	if err = json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			dates := make([]time.Time, len(c.Paths[0]))
			start := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
			for i := range dates {
				dates[i] = start.AddDate(0, 0, i)
			}
			gaps := risk.FindGaps(forecast.Result{Dates: dates, Balances: c.Paths}, 0)
			if c.DateIndex == nil {
				if len(gaps) != 0 {
					t.Fatal("horizon event is not a daily alarm")
				}
				return
			}
			if len(gaps) != 1 || !gaps[0].Date.Equal(dates[*c.DateIndex]) {
				t.Fatalf("wrong first gap: %+v", gaps)
			}
			if math.Abs(gaps[0].Probability-c.Probability) > 1e-9 || math.Abs(gaps[0].Shortfall.Float()-c.Shortfall) > 1e-9 {
				t.Fatalf("wrong probability or shortfall: %+v", gaps)
			}
		})
	}
}
