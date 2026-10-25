// Package obligations defines the read-only connector contract shared by the
// application and its own demonstration bank/accounting API.
package obligations

import (
	"errors"
	"strings"
	"time"
)

type Feed struct {
	CompanyINN string `json:"company_inn"`
	AsOf       string `json:"as_of"`
	Complete   bool   `json:"complete"`
	DataMode   string `json:"data_mode,omitempty"`
	Items      []Item `json:"items"`
}

type Item struct {
	ExternalID       string `json:"external_id"`
	Kind             string `json:"kind"`
	Title            string `json:"title"`
	DueDate          string `json:"due_date,omitempty"`
	AmountKopecks    int64  `json:"amount_kopecks"`
	Direction        string `json:"direction"`
	Status           string `json:"status"`
	CounterpartyName string `json:"counterparty_name,omitempty"`
	CounterpartyINN  string `json:"counterparty_inn,omitempty"`
	Additional       *bool  `json:"additional,omitempty"`
	TaxKind          string `json:"tax_kind,omitempty"`
	Period           string `json:"period,omitempty"`
	Year             int    `json:"year,omitempty"`
	RelatedEventID   string `json:"related_event_id,omitempty"`
	DocumentNumber   string `json:"document_number,omitempty"`
}

func (f Feed) Validate(kind string) error {
	invalid := errors.New("invalid obligation snapshot")
	if kind != "bank" && kind != "tax" || !f.Complete || f.Items == nil || len(f.Items) > 10000 || !validINN(f.CompanyINN) {
		return invalid
	}
	if f.DataMode != "" && f.DataMode != "demo" && f.DataMode != "live" {
		return invalid
	}
	if _, e := time.Parse("2006-01-02", f.AsOf); e != nil {
		return invalid
	}
	seen := map[string]bool{}
	for _, item := range f.Items {
		if len(item.RelatedEventID) > 64 || len([]rune(item.DocumentNumber)) > 1024 {
			return invalid
		}
		if item.ExternalID == "" || len(item.ExternalID) > 200 || seen[item.ExternalID] || strings.TrimSpace(item.Title) == "" || len([]rune(item.Title)) > 500 || item.AmountKopecks < 0 || item.AmountKopecks > 1_000_000_000_000_000 || item.Direction != "in" && item.Direction != "out" || item.Status != "expected" && item.Status != "paid" && item.Status != "cancelled" || item.Status == "expected" && item.AmountKopecks == 0 || len([]rune(item.CounterpartyName)) > 1024 || item.CounterpartyINN != "" && !validINN(item.CounterpartyINN) {
			return invalid
		}
		seen[item.ExternalID] = true
		if kind == "bank" {
			if item.Kind != "loan_payment" && item.Kind != "salary" && item.Kind != "payment_order" || item.DueDate == "" {
				return invalid
			}
		} else if item.Kind != "tax" || item.Direction != "out" {
			return invalid
		}
		if item.Kind == "tax" {
			if len(item.Period) > 500 || item.Year != 0 && (item.Year < 2024 || item.Year > 2100) {
				return invalid
			}
			known := item.TaxKind == ""
			for _, kind := range []string{"usn_advance", "usn_annual", "vat", "enp", "contributions", "other"} {
				known = known || item.TaxKind == kind
			}
			if !known {
				return invalid
			}
		}
		if item.DueDate != "" {
			if _, e := time.Parse("2006-01-02", item.DueDate); e != nil {
				return invalid
			}
		} else if item.TaxKind == "" || item.Period == "" || item.Year < 2024 || item.Year > 2100 {
			return invalid
		}
	}
	return nil
}

func validINN(value string) bool {
	if len(value) != 10 && len(value) != 12 {
		return false
	}
	for _, c := range value {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}
