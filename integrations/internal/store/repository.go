package store

import "github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"

type Repository interface {
	Save(contracts.ImportBatch) (contracts.ImportBatch, error)
	GetOperations(companyID string) ([]contracts.Operation, error)
	GetPlans(companyID string) ([]contracts.PlannedEvent, error)
	GetBatches(companyID string) ([]contracts.ImportBatch, error)
	RecordRun(companyID, sourceKind string, status int) error
	GetRuns(companyID string) ([]SyncRun, error)
	SaveMarketplace(companyID string, entries []MarketplaceEntry) (int, int, error)
	GetMarketplace(companyID string) ([]MarketplaceEntry, error)
	SaveRisks(companyID string, signals []RiskSignal) (int, int, error)
	GetRisks(companyID string) ([]RiskSignal, error)
	SaveCounterparty(companyID string, party Counterparty) (Counterparty, error)
	GetCounterparties(companyID string) ([]Counterparty, error)
}

type Counterparty struct {
	ExternalID string `json:"external_id"`
	SourceKind string `json:"source_kind"`
	INN        string `json:"inn"`
	KPP        string `json:"kpp,omitempty"`
	OGRN       string `json:"ogrn"`
	Name       string `json:"name"`
	Type       string `json:"type"`
	Status     string `json:"status"`
	CheckedAt  string `json:"checked_at"`
	SourceURL  string `json:"source_url"`
	DataMode   string `json:"data_mode"`
	Version    int64  `json:"version"`
}

type RiskSignal struct {
	ExternalID    string `json:"external_id"`
	SourceKind    string `json:"source_kind"`
	SubjectINN    string `json:"subject_inn"`
	Kind          string `json:"kind"`
	AmountKopecks int64  `json:"amount_kopecks"`
	DatasetAsOf   string `json:"dataset_as_of"`
	PublishedAt   string `json:"published_at"`
	RetrievedAt   string `json:"retrieved_at"`
	SourceURL     string `json:"source_url"`
	DataMode      string `json:"data_mode"`
	Version       int64  `json:"version"`
}

type MarketplaceEntry struct {
	ExternalID       string           `json:"external_id"`
	SourceKind       string           `json:"source_kind"`
	Category         string           `json:"category"`
	AmountKopecks    int64            `json:"amount_kopecks"`
	Components       map[string]int64 `json:"components_kopecks,omitempty"`
	Currency         string           `json:"currency"`
	OccurredAt       string           `json:"occurred_at,omitempty"`
	ObservedAt       string           `json:"observed_at"`
	DataMode         string           `json:"data_mode"`
	ForecastEligible bool             `json:"forecast_eligible"`
	Version          int64            `json:"version"`
}

type SyncRun struct {
	ID         int64  `json:"id"`
	CompanyID  string `json:"company_id"`
	SourceKind string `json:"source_kind"`
	Status     int    `json:"http_status"`
	StartedAt  string `json:"started_at"`
}
