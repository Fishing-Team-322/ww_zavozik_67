package scheduler

import (
	"context"
	"crypto/rand"
	"math/big"
	"time"
)

// Run starts an independent periodic source loop. A failed source backs off
// without delaying the others. Work is cancelled on service shutdown.
func Run(ctx context.Context, interval, timeout time.Duration, job func(context.Context) error) {
	if interval <= 0 || timeout <= 0 || job == nil {
		return
	}
	go func() {
		failures := 0
		for {
			delay := interval
			if failures > 0 {
				delay = time.Second
				for i := 1; i < failures && delay < interval; i++ {
					delay *= 2
				}
				if delay > interval {
					delay = interval
				}
			}
			if n, err := rand.Int(rand.Reader, big.NewInt(int64(delay/10+1))); err == nil {
				delay += time.Duration(n.Int64())
			}
			timer := time.NewTimer(delay)
			select {
			case <-ctx.Done():
				timer.Stop()
				return
			case <-timer.C:
			}
			jobCtx, cancel := context.WithTimeout(ctx, timeout)
			err := job(jobCtx)
			cancel()
			if err != nil {
				if failures < 16 {
					failures++
				}
			} else {
				failures = 0
			}
		}
	}()
}
