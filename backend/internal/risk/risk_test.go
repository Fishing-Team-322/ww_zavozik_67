package risk

import (
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func TestFindGapsAndSafeToSpend(t *testing.T) {
	start := time.Date(2025, 3, 1, 0, 0, 0, 0, time.UTC)
	r := forecast.Result{
		OpeningBalance: 1000,
		Dates:          []time.Time{start, start.AddDate(0, 0, 1), start.AddDate(0, 0, 2)},
		Balances: [][]float64{
			{900, 400, 700},
			{900, 600, 800},
			{900, 300, 650},
			{900, 700, 900},
		},
	}
	gaps := FindGaps(r, 500)
	if len(gaps) != 1 {
		t.Fatalf("want 1 gap, got %d", len(gaps))
	}
	g := gaps[0]
	if !g.Date.Equal(start.AddDate(0, 0, 1)) || g.Probability != 0.5 {
		t.Errorf("bad gap: %+v", g)
	}
	if got := SafeToSpend(r, 200, 0); got != 100 {
		t.Errorf("safe to spend: got %v, want 100", got)
	}
	if got := FindGaps(r, 100); len(got) != 0 {
		t.Errorf("no gap expected, got %+v", got)
	}
}
