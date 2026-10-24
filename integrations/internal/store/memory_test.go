package store

import (
	"sync"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
)

func TestConcurrentDedup(t *testing.T) {
	m := NewMemory()
	const workers = 20
	var wg sync.WaitGroup
	accepted := make(chan int, workers)
	for range workers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			batch := contracts.NewBatch("one")
			batch.Operations = []contracts.Operation{{DedupKey: "same"}}
			batch.Stats = contracts.Stats{Parsed: 1, Accepted: 1}
			accepted <- m.Add(batch).Stats.Accepted
		}()
	}
	wg.Wait()
	close(accepted)
	total := 0
	for n := range accepted {
		total += n
	}
	if total != 1 || len(m.Batches("one")) != workers {
		t.Fatalf("accepted=%d, batches=%d", total, len(m.Batches("one")))
	}
}
