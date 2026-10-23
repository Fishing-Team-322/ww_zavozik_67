package forecast

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

type failing struct{}

func (failing) Forecast(context.Context, StochasticRequest) (StochasticForecast, error) {
	return StochasticForecast{}, errors.New("down")
}
func (failing) Models(context.Context) ([]ModelInfo, error) { return nil, errors.New("down") }

func history(days int) []domain.DailyFlow {
	start := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	h := make([]domain.DailyFlow, days)
	for i := range h {
		h[i] = domain.DailyFlow{Date: start.AddDate(0, 0, i)}
		if wd := h[i].Date.Weekday(); wd != time.Saturday && wd != time.Sunday {
			h[i].Inflow, h[i].Outflow = 100, 40
		}
	}
	return h
}

func TestAssemblerFallsBackAndAddsComponents(t *testing.T) {
	h := history(70)
	asOf := h[len(h)-1].Date
	a := Assembler{Primary: failing{}, Fallback: SeasonalNaive{}}
	res, err := a.Build(context.Background(), Input{
		AsOf:           asOf,
		OpeningBalance: 1000,
		Deterministic:  []ComponentFlow{{Date: asOf.AddDate(0, 0, 3), Key: "tax", Amount: -500}},
		Stochastic:     StochasticRequest{History: h, Horizon: 14, NPaths: 50, Seed: 1},
	})
	if err != nil {
		t.Fatal(err)
	}
	if res.Stochastic.ModelUsed != NaiveName {
		t.Fatalf("expected fallback, got %s", res.Stochastic.ModelUsed)
	}
	// История детерминированная: каждый будний день +60, выходные 0.
	want := 1000.0
	for d, date := range res.Dates {
		if wd := date.Weekday(); wd != time.Saturday && wd != time.Sunday {
			want += 60
		}
		if d == 2 {
			want -= 500
		}
		if got := res.Quantile(0.5)[d]; got != want {
			t.Fatalf("day %d (%s): got %v, want %v", d, date.Format(domain.DateLayout), got, want)
		}
	}
}

func TestNaiveLowConfidence(t *testing.T) {
	sf, _ := SeasonalNaive{}.Forecast(context.Background(), StochasticRequest{History: history(10), Horizon: 7, NPaths: 3})
	if !sf.LowConfidence {
		t.Error("10 days of history must be low confidence")
	}
}
