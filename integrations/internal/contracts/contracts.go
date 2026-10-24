package contracts

import (
	"errors"
	"strings"
)

const SchemaVersion = "1.0"
const SourceKind = "onec_bank_file"
const SourceOneCOData = "onec_odata"

type Identity struct {
	CompanyID      string
	CompanyINN     string
	CompanyAccount string
}

func (i Identity) Validate() error {
	if len(i.CompanyID) == 0 || len(i.CompanyID) > 128 || strings.TrimSpace(i.CompanyID) != i.CompanyID {
		return errors.New("company_id is required (max 128 characters, no surrounding whitespace)")
	}
	if !digits(i.CompanyINN) || (len(i.CompanyINN) != 10 && len(i.CompanyINN) != 12) {
		return errors.New("company_inn must contain 10 or 12 digits")
	}
	if !digits(i.CompanyAccount) || len(i.CompanyAccount) != 20 {
		return errors.New("company_account must contain 20 digits")
	}
	return nil
}

func digits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

type Operation struct {
	ExternalID        string `json:"external_id,omitempty"`
	DedupKey          string `json:"dedup_key"`
	Date              string `json:"date"`
	AmountKopecks     int64  `json:"amount_kopecks"`
	Direction         string `json:"direction"`
	CounterpartyINN   string `json:"counterparty_inn"`
	CounterpartyName  string `json:"counterparty_name"`
	Purpose           string `json:"purpose"`
	SourceKind        string `json:"source_kind"`
	Account           string `json:"account"`
	Executed          bool   `json:"executed"`
	BalanceEODKopecks *int64 `json:"balance_eod_kopecks,omitempty"`
}

type Issue struct {
	Code    string `json:"code"`
	Section int    `json:"section"`
	Message string `json:"message"`
}

type Stats struct {
	Parsed     int `json:"parsed"`
	Accepted   int `json:"accepted"`
	Duplicates int `json:"duplicates"`
	Rejected   int `json:"rejected"`
}

// PlannedEvent is reserved for future pullers. A bank statement never emits one.
type PlannedEvent struct {
	ExternalID    string `json:"external_id"`
	Date          string `json:"date"`
	AmountKopecks int64  `json:"amount_kopecks"`
	Direction     string `json:"direction"`
	Title         string `json:"title"`
	SourceKind    string `json:"source_kind"`
	Status        string `json:"status"`
}

type ImportBatch struct {
	SchemaVersion string         `json:"schema_version"`
	CompanyID     string         `json:"company_id"`
	SourceKind    string         `json:"source_kind"`
	SourceMode    string         `json:"source_mode"`
	ImportID      string         `json:"import_id"`
	ImportedAt    string         `json:"imported_at"`
	Operations    []Operation    `json:"operations"`
	PlannedEvents []PlannedEvent `json:"planned_events"`
	Issues        []Issue        `json:"issues"`
	Stats         Stats          `json:"stats"`
}

func NewBatch(companyID string) ImportBatch {
	return NewBatchFor(companyID, SourceKind, "file")
}

func NewBatchFor(companyID, kind, mode string) ImportBatch {
	return ImportBatch{SchemaVersion: SchemaVersion, CompanyID: companyID, SourceKind: kind, SourceMode: mode, Operations: []Operation{}, PlannedEvents: []PlannedEvent{}, Issues: []Issue{}}
}
