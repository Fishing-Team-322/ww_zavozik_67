package store

import (
	"sync"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
)

// Memory is process-local. All writes and reads are synchronized.
type Memory struct {
	mu      sync.RWMutex
	seen    map[string]map[string]bool
	batches map[string][]contracts.ImportBatch
}

func NewMemory() *Memory {
	return &Memory{seen: make(map[string]map[string]bool), batches: make(map[string][]contracts.ImportBatch)}
}

func (m *Memory) Add(batch contracts.ImportBatch) contracts.ImportBatch {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.seen[batch.CompanyID] == nil {
		m.seen[batch.CompanyID] = make(map[string]bool)
	}
	fresh := make([]contracts.Operation, 0, len(batch.Operations))
	for _, op := range batch.Operations {
		if m.seen[batch.CompanyID][op.DedupKey] {
			batch.Stats.Duplicates++
			batch.Stats.Accepted--
			continue
		}
		m.seen[batch.CompanyID][op.DedupKey] = true
		fresh = append(fresh, op)
	}
	batch.Operations = fresh
	m.batches[batch.CompanyID] = append(m.batches[batch.CompanyID], batch)
	return batch
}

func (m *Memory) Batches(companyID string) []contracts.ImportBatch {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := append([]contracts.ImportBatch{}, m.batches[companyID]...)
	return out
}
