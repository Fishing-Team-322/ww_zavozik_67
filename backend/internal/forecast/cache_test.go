package forecast

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

type countingForecast struct {
	calls            atomic.Int64
	fail             bool
	entered, release chan struct{}
}

func (c *countingForecast) Models(context.Context) ([]ModelInfo, error) { return nil, nil }
func (c *countingForecast) Forecast(ctx context.Context, r StochasticRequest) (StochasticForecast, error) {
	c.calls.Add(1)
	if c.entered != nil {
		select {
		case c.entered <- struct{}{}:
		default:
		}
		select {
		case <-ctx.Done():
			return StochasticForecast{}, ctx.Err()
		case <-c.release:
		}
	}
	if c.fail {
		return StochasticForecast{}, errors.New("unavailable")
	}
	return StochasticForecast{Inflow: [][]float64{{42}}, Outflow: [][]float64{{10}}, Warnings: []string{"original"}}, nil
}
func TestMLCacheIsolationInvalidationAndExpiry(t *testing.T) {
	primary := &countingForecast{}
	c := NewCachedForecaster(primary, time.Minute, 2).(*CachedForecaster)
	now := time.Now()
	c.now = func() time.Time { return now }
	r := StochasticRequest{CompanyID: "one", Model: "auto", Horizon: 30, Seed: 67, History: []domain.DailyFlow{{Date: now, Inflow: 100}}}
	a, e := c.Forecast(context.Background(), r)
	if e != nil {
		t.Fatal(e)
	}
	a.Inflow[0][0] = 999
	a.Warnings[0] = "mutated"
	b, e := c.Forecast(context.Background(), r)
	if e != nil || b.Inflow[0][0] != 42 || b.Warnings[0] != "original" || primary.calls.Load() != 1 {
		t.Fatal("cache is not isolated", b, e)
	}
	r.CompanyID = "two"
	c.Forecast(context.Background(), r)
	r.History[0].Inflow = 101
	c.Forecast(context.Background(), r)
	if primary.calls.Load() != 3 || len(c.entries) > 2 {
		t.Fatal("history/company key or capacity")
	}
	now = now.Add(2 * time.Minute)
	c.Forecast(context.Background(), r)
	if primary.calls.Load() != 4 {
		t.Fatal("expired value reused")
	}
	primary.fail = true
	r.Model = "other"
	c.Forecast(context.Background(), r)
	c.Forecast(context.Background(), r)
	if primary.calls.Load() != 6 {
		t.Fatal("error cached")
	}
}
func TestMLCacheSingleFlightAndCanceledWaiter(t *testing.T) {
	p := &countingForecast{entered: make(chan struct{}, 1), release: make(chan struct{})}
	c := NewCachedForecaster(p, time.Minute, 2)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		if _, e := c.Forecast(context.Background(), StochasticRequest{}); e != nil {
			t.Error(e)
		}
	}()
	<-p.entered
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, e := c.Forecast(ctx, StochasticRequest{}); !errors.Is(e, context.Canceled) {
		t.Fatal(e)
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		if _, e := c.Forecast(context.Background(), StochasticRequest{}); e != nil {
			t.Error(e)
		}
	}()
	close(p.release)
	wg.Wait()
	if p.calls.Load() != 1 {
		t.Fatal("identical requests called ML twice")
	}
}
