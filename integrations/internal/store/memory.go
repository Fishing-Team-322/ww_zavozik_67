package store

import (
	"reflect"
	"sync"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
)

// Memory is process-local. All writes and reads are synchronized.
type Memory struct {
	mu          sync.RWMutex
	seen        map[string]map[string]contracts.Operation
	plans       map[string]map[string]contracts.PlannedEvent
	batches     map[string][]contracts.ImportBatch
	runs        map[string][]SyncRun
	marketplace map[string]map[string]MarketplaceEntry
	risks       map[string]map[string]RiskSignal
}

func NewMemory() *Memory {
	return &Memory{seen: make(map[string]map[string]contracts.Operation), plans: make(map[string]map[string]contracts.PlannedEvent), batches: make(map[string][]contracts.ImportBatch), runs: make(map[string][]SyncRun), marketplace: make(map[string]map[string]MarketplaceEntry), risks: make(map[string]map[string]RiskSignal)}
}

func (m *Memory) Add(batch contracts.ImportBatch) contracts.ImportBatch {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.seen[batch.CompanyID] == nil {
		m.seen[batch.CompanyID] = make(map[string]contracts.Operation)
	}
	fresh := make([]contracts.Operation, 0, len(batch.Operations))
	for _, op := range batch.Operations {
		if old, exists := m.seen[batch.CompanyID][op.DedupKey]; exists {
			before, after := old, op
			before.Version, after.Version = 0, 0
			if reflect.DeepEqual(before, after) {
				batch.Stats.Duplicates++
				batch.Stats.Accepted--
				continue
			}
			op.Version = old.Version + 1
		} else {
			op.Version = 1
		}
		m.seen[batch.CompanyID][op.DedupKey] = op
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

func (m *Memory) Save(batch contracts.ImportBatch) (contracts.ImportBatch, error) {
	return m.Add(batch), nil
}

func (m *Memory) GetPlans(companyID string) ([]contracts.PlannedEvent, error) {
	return m.Plans(companyID), nil
}

func (m *Memory) GetBatches(companyID string) ([]contracts.ImportBatch, error) {
	return m.Batches(companyID), nil
}

func (m *Memory) GetOperations(companyID string) ([]contracts.Operation, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]contracts.Operation, 0, len(m.seen[companyID]))
	for _, op := range m.seen[companyID] {
		out = append(out, op)
	}
	return out, nil
}

func (m *Memory) RecordRun(companyID, sourceKind string, status int) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.runs[companyID] = append(m.runs[companyID], SyncRun{ID: int64(len(m.runs[companyID]) + 1), CompanyID: companyID, SourceKind: sourceKind, Status: status})
	return nil
}

func (m *Memory) GetRuns(companyID string) ([]SyncRun, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return append([]SyncRun{}, m.runs[companyID]...), nil
}

func (m *Memory) SaveMarketplace(companyID string, entries []MarketplaceEntry) (int, int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.marketplace[companyID] == nil {
		m.marketplace[companyID] = make(map[string]MarketplaceEntry)
	}
	changed, duplicates := 0, 0
	for _, entry := range entries {
		key := entry.SourceKind + "\x00" + entry.ExternalID
		if old, ok := m.marketplace[companyID][key]; ok {
			before, after := old, entry
			before.Version, after.Version = 0, 0
			before.ObservedAt, after.ObservedAt = "", ""
			if reflect.DeepEqual(before, after) {
				duplicates++
				continue
			}
			entry.Version = old.Version + 1
		} else {
			entry.Version = 1
		}
		m.marketplace[companyID][key] = entry
		changed++
	}
	return changed, duplicates, nil
}

func (m *Memory) GetMarketplace(companyID string) ([]MarketplaceEntry, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]MarketplaceEntry, 0, len(m.marketplace[companyID]))
	for _, entry := range m.marketplace[companyID] {
		out = append(out, entry)
	}
	return out, nil
}

func (m *Memory) SaveRisks(companyID string, signals []RiskSignal) (int, int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.risks[companyID] == nil {
		m.risks[companyID] = make(map[string]RiskSignal)
	}
	changed, duplicates := 0, 0
	for _, signal := range signals {
		key := signal.SourceKind + "\x00" + signal.ExternalID
		if old, ok := m.risks[companyID][key]; ok {
			before, after := old, signal
			before.Version, after.Version = 0, 0
			before.RetrievedAt, after.RetrievedAt = "", ""
			if reflect.DeepEqual(before, after) {
				duplicates++
				continue
			}
			signal.Version = old.Version + 1
		} else {
			signal.Version = 1
		}
		m.risks[companyID][key] = signal
		changed++
	}
	return changed, duplicates, nil
}
func (m *Memory) GetRisks(companyID string) ([]RiskSignal, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]RiskSignal, 0, len(m.risks[companyID]))
	for _, signal := range m.risks[companyID] {
		out = append(out, signal)
	}
	return out, nil
}
