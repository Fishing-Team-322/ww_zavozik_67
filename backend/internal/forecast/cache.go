package forecast

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"sync"
	"time"
)

// CachedForecaster reuses successful ML paths when only additional plans change.
// The key includes company, complete history, model, horizon, seed and flow scope.
// Values are private deep copies; failures and fallback responses are never cached.
type CachedForecaster struct {
	primary StochasticForecaster
	ttl     time.Duration
	limit   int
	mu      sync.Mutex
	entries map[[32]byte]forecastEntry
	flights map[[32]byte]*forecastFlight
	now     func() time.Time
}
type forecastEntry struct {
	value          StochasticForecast
	expires, saved time.Time
}
type forecastFlight struct {
	done  chan struct{}
	value StochasticForecast
	err   error
}

func NewCachedForecaster(primary StochasticForecaster, ttl time.Duration, limit int) StochasticForecaster {
	if primary == nil {
		return nil
	}
	if ttl <= 0 {
		ttl = time.Minute
	}
	if limit < 1 {
		limit = 16
	}
	return &CachedForecaster{primary: primary, ttl: ttl, limit: limit, entries: map[[32]byte]forecastEntry{}, flights: map[[32]byte]*forecastFlight{}, now: time.Now}
}
func (c *CachedForecaster) Models(ctx context.Context) ([]ModelInfo, error) {
	return c.primary.Models(ctx)
}
func copyStochastic(s StochasticForecast) StochasticForecast {
	r := Result{Stochastic: s}.Clone()
	return r.Stochastic
}
func (c *CachedForecaster) Forecast(ctx context.Context, req StochasticRequest) (StochasticForecast, error) {
	if e := ctx.Err(); e != nil {
		return StochasticForecast{}, e
	}
	raw, e := json.Marshal(req)
	if e != nil {
		return StochasticForecast{}, e
	}
	key := sha256.Sum256(raw)
	c.mu.Lock()
	now := c.now()
	if cached, yes := c.entries[key]; yes && now.Before(cached.expires) {
		value := copyStochastic(cached.value)
		c.mu.Unlock()
		return value, nil
	}
	if pending, yes := c.flights[key]; yes {
		c.mu.Unlock()
		select {
		case <-ctx.Done():
			return StochasticForecast{}, ctx.Err()
		case <-pending.done:
			return copyStochastic(pending.value), pending.err
		}
	}
	// Bound bookkeeping even if many different companies request concurrently.
	if len(c.flights) >= c.limit {
		c.mu.Unlock()
		return c.primary.Forecast(ctx, req)
	}
	pending := &forecastFlight{done: make(chan struct{})}
	c.flights[key] = pending
	c.mu.Unlock()
	value, err := c.primary.Forecast(ctx, req)
	if err == nil {
		err = ctx.Err()
	}
	c.mu.Lock()
	if err == nil && !value.FallbackUsed {
		if len(c.entries) >= c.limit {
			var oldest [32]byte
			var oldestTime time.Time
			for k, v := range c.entries {
				if oldestTime.IsZero() || v.saved.Before(oldestTime) {
					oldest, oldestTime = k, v.saved
				}
			}
			delete(c.entries, oldest)
		}
		t := c.now()
		c.entries[key] = forecastEntry{value: copyStochastic(value), saved: t, expires: t.Add(c.ttl)}
	}
	pending.value, pending.err = copyStochastic(value), err
	delete(c.flights, key)
	close(pending.done)
	c.mu.Unlock()
	return value, err
}
