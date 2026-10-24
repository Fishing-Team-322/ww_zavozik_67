package store

import (
	"reflect"
	"sync"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
)

// Memory is process-local. All writes and reads are synchronized.
type Memory struct {
	mu      sync.RWMutex
	seen    map[string]map[string]bool
	plans   map[string]map[string]contracts.PlannedEvent
	batches map[string][]contracts.ImportBatch
}

func NewMemory() *Memory {
	return &Memory{seen: make(map[string]map[string]bool), plans: make(map[string]map[string]contracts.PlannedEvent), batches: make(map[string][]contracts.ImportBatch)}
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
	if m.plans[batch.CompanyID] == nil {
		m.plans[batch.CompanyID] = make(map[string]contracts.PlannedEvent)
	}
	freshPlans := make([]contracts.PlannedEvent, 0, len(batch.PlannedEvents))
	for _, event := range batch.PlannedEvents {
		key := event.SourceKind + "\x00" + event.ExternalID
		if old, exists := m.plans[batch.CompanyID][key]; exists {
			before, after := old, event
			before.Version, after.Version = 0, 0
			before.ObservedAt, after.ObservedAt = "", ""
			if reflect.DeepEqual(before, after) {
				batch.Stats.Duplicates++
				batch.Stats.Accepted--
				continue
			}
			event.Version = old.Version + 1
		} else {
			event.Version = 1
		}
		m.plans[batch.CompanyID][key] = event
		freshPlans = append(freshPlans, event)
	}
	batch.PlannedEvents = freshPlans
	m.batches[batch.CompanyID] = append(m.batches[batch.CompanyID], batch)
	return batch
}

func (m *Memory) Plans(companyID string) []contracts.PlannedEvent {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]contracts.PlannedEvent, 0, len(m.plans[companyID]))
	for _, event := range m.plans[companyID] {
		out = append(out, event)
	}
	return out
}

func (m *Memory) Batches(companyID string) []contracts.ImportBatch {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := append([]contracts.ImportBatch{}, m.batches[companyID]...)
	return out
}
