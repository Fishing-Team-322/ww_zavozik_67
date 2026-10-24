package scheduler

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"
)

func TestRunRetriesAndStops(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	var calls atomic.Int32
	Run(ctx, 20*time.Millisecond, time.Second, func(context.Context) error {
		if calls.Add(1) == 1 {
			return errors.New("temporary")
		}
		return nil
	})
	deadline := time.After(time.Second)
	for calls.Load() < 2 {
		select {
		case <-deadline:
			t.Fatal("scheduler did not retry")
		case <-time.After(10 * time.Millisecond):
		}
	}
	cancel()
	before := calls.Load()
	time.Sleep(80 * time.Millisecond)
	if calls.Load() != before {
		t.Fatal("scheduler ran after cancellation")
	}
}
