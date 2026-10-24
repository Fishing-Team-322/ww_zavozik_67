package product

import (
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func TestIncrementalPathsSurviveAdvancingHistoryWindow(t *testing.T) {
	day := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	previous := forecast.StochasticRequest{History: []domain.DailyFlow{{Date: day, Inflow: 10}, {Date: day.AddDate(0, 0, 1), Inflow: 20}}, Transactions: []forecast.HistoryTransaction{{ID: "first", Date: day, Amount: 10}, {ID: "second", Date: day.AddDate(0, 0, 1), Amount: 20}}, NPaths: 1, Horizon: 4}
	current := forecast.StochasticRequest{History: []domain.DailyFlow{{Date: day.AddDate(0, 0, 1), Inflow: 20}, {Date: day.AddDate(0, 0, 2), Inflow: 30}}, Transactions: []forecast.HistoryTransaction{{ID: "second", Date: day.AddDate(0, 0, 1), Amount: 20}, {ID: "third", Date: day.AddDate(0, 0, 2), Amount: 30}}, NPaths: 1, Horizon: 2}
	saved := forecast.StochasticForecast{Dates: []time.Time{day.AddDate(0, 0, 2), day.AddDate(0, 0, 3), day.AddDate(0, 0, 4), day.AddDate(0, 0, 5)}, Inflow: [][]float64{{1, 2, 3, 4}}, Outflow: [][]float64{{0, 0, 0, 0}}}
	out, ok := reuseForecastPaths(previous, current, saved)
	if !ok || len(out.Dates) != 2 || out.Inflow[0][0] != 2 || out.UpdateMode != "updated_from_actuals" {
		t.Fatal("rolling history caused unnecessary model inference", out, ok)
	}
	current.Transactions[0].Purpose = "Corrected historical purpose"
	if _, ok = reuseForecastPaths(previous, current, saved); ok {
		t.Fatal("changed token history was reused")
	}
}
