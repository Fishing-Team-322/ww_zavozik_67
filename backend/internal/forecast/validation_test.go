package forecast

import (
	"context"
	"math"
	"testing"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

func TestFallbackRejectsInvalidInput(t *testing.T) {
	cases := map[string]func(*StochasticRequest){
		"empty": func(r *StochasticRequest) { r.History = nil },
		"all missing": func(r *StochasticRequest) {
			for i := range r.History {
				r.History[i].Missing = true
			}
		},
		"negative horizon": func(r *StochasticRequest) { r.Horizon = -1 },
		"too large":        func(r *StochasticRequest) { r.Horizon, r.NPaths = 366, 5000 },
		"negative seed":    func(r *StochasticRequest) { r.Seed = -1 },
		"scope":            func(r *StochasticRequest) { r.FlowScope = "residual_only" },
		"date gap":         func(r *StochasticRequest) { r.History[4].Date = r.History[3].Date },
		"date overflow": func(r *StochasticRequest) {
			r.History = []domain.DailyFlow{{Date: time.Date(9999, 12, 31, 0, 0, 0, 0, time.UTC)}}
		},
		"nan":      func(r *StochasticRequest) { r.History[0].Inflow = domain.Money(math.NaN()) },
		"negative": func(r *StochasticRequest) { r.History[0].Outflow = -1 },
		"overflow": func(r *StochasticRequest) { r.History[0].Outflow = 1e308 },
		"category": func(r *StochasticRequest) { r.History[0].ByCategory = map[domain.Category]domain.Money{"bogus": 1} },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			r := StochasticRequest{History: history(10), Horizon: 7, NPaths: 10}
			mutate(&r)
			// Both direct calls and service outage must reject the bad request.
			_, err := (SeasonalNaive{}).Forecast(context.Background(), r)
			if status.Code(err) != codes.InvalidArgument && status.Code(err) != codes.FailedPrecondition {
				t.Fatalf("unexpected direct result: %v", err)
			}
			a := Assembler{Primary: failing{}, Fallback: SeasonalNaive{}}
			_, err = a.Build(context.Background(), Input{AsOf: history(10)[9].Date, Stochastic: r})
			if status.Code(err) != codes.InvalidArgument && status.Code(err) != codes.FailedPrecondition {
				t.Fatalf("unexpected outage result: %v", err)
			}
		})
	}
}

func TestFallbackDoesNotInventZeroForUnknownWeekday(t *testing.T) {
	h := []domain.DailyFlow{{Date: time.Date(2026, 10, 20, 0, 0, 0, 0, time.UTC), Inflow: 100, Outflow: 30}}
	r := StochasticRequest{History: h, Horizon: 7, NPaths: 2, Seed: 42}
	sf, err := (SeasonalNaive{}).Forecast(context.Background(), r)
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range sf.Inflow {
		for _, v := range p {
			if v != 100 {
				t.Fatalf("unobserved weekday was treated as a zero: %v", sf.Inflow)
			}
		}
	}
	if !sf.LowConfidence || sf.FlowScope != BusinessFlowScope || sf.ModelVersion == "" {
		t.Fatalf("missing metadata: %+v", sf)
	}
}

func TestFallbackRejectsEmptyRecentWindowAndCancellation(t *testing.T) {
	h := history(100)
	for i := 44; i < len(h); i++ {
		h[i].Missing = true
	}
	r := StochasticRequest{History: h, Horizon: 7, NPaths: 10}
	if _, err := (SeasonalNaive{}).Forecast(context.Background(), r); status.Code(err) != codes.FailedPrecondition {
		t.Fatalf("got %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := (SeasonalNaive{}).Forecast(ctx, r); err != context.Canceled {
		t.Fatalf("got %v", err)
	}
}

func TestAssemblerRejectsDateShift(t *testing.T) {
	h := history(70)
	a := Assembler{Fallback: SeasonalNaive{}}
	_, err := a.Build(context.Background(), Input{AsOf: h[68].Date, Stochastic: StochasticRequest{History: h, Horizon: 7, NPaths: 2}})
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("got %v", err)
	}
}
