package store

import "github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"

type Repository interface {
	Save(contracts.ImportBatch) (contracts.ImportBatch, error)
	GetOperations(companyID string) ([]contracts.Operation, error)
	GetPlans(companyID string) ([]contracts.PlannedEvent, error)
	GetBatches(companyID string) ([]contracts.ImportBatch, error)
	RecordRun(companyID, sourceKind string, status int) error
	GetRuns(companyID string) ([]SyncRun, error)
}

type SyncRun struct {
	ID         int64  `json:"id"`
	CompanyID  string `json:"company_id"`
	SourceKind string `json:"source_kind"`
	Status     int    `json:"http_status"`
	StartedAt  string `json:"started_at"`
}
