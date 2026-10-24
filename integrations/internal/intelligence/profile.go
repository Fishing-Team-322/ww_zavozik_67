package intelligence

import (
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fnsregistry"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

type FieldSource struct {
	Provider string `json:"provider"`
	ActualAt string `json:"actual_at"`
	Value    string `json:"value"`
}
type Conflict struct {
	Field  string        `json:"field"`
	Values []FieldSource `json:"values"`
}
type Profile struct {
	INN                string                   `json:"inn"`
	OGRN               string                   `json:"ogrn,omitempty"`
	EntityType         string                   `json:"entity_type,omitempty"`
	Name               string                   `json:"name,omitempty"`
	RegistrationStatus string                   `json:"registration_status"`
	Status             string                   `json:"status"`
	ActualAt           string                   `json:"actual_at,omitempty"`
	FieldSources       map[string][]FieldSource `json:"field_sources"`
	Conflicts          []Conflict               `json:"conflicts"`
	RiskSignals        []store.RiskSignal       `json:"risk_signals"`
}

func Build(id string, records []fnsregistry.Record, parties []store.Counterparty, risks []store.RiskSignal, now time.Time) Profile {
	p := Profile{INN: id, Status: "NOT_FOUND", RegistrationStatus: "UNKNOWN", FieldSources: map[string][]FieldSource{}, Conflicts: []Conflict{}, RiskSignals: []store.RiskSignal{}}
	var official *fnsregistry.Record
	for i := range records {
		r := &records[i]
		if official == nil || r.ActualAt > official.ActualAt {
			official = r
		}
	}
	if official != nil {
		p.INN = official.INN
		p.OGRN = official.OGRN
		p.EntityType = official.EntityType
		p.Name = official.Name
		p.RegistrationStatus = official.RegistrationStatus
		p.ActualAt = official.ActualAt
		p.Status = "VERIFIED"
		if date, err := time.Parse("2006-01-02", official.ActualAt); err != nil || now.Sub(date) > 90*24*time.Hour {
			p.Status = "STALE"
		}
		for field, value := range map[string]string{"inn": official.INN, "ogrn": official.OGRN, "name": official.Name, "registration_status": official.RegistrationStatus, "entity_type": official.EntityType} {
			if value != "" {
				p.FieldSources[field] = append(p.FieldSources[field], FieldSource{Provider: official.Source, ActualAt: official.ActualAt, Value: value})
			}
		}
	}
	for _, d := range parties {
		if d.INN != id && (official == nil || d.INN != official.INN) && d.OGRN != id {
			continue
		}
		typ := d.Type
		if typ == "LEGAL" {
			typ = "LEGAL_ENTITY"
		}
		if p.Status == "NOT_FOUND" {
			p.Status = "UNKNOWN"
			p.INN = d.INN
			p.OGRN = d.OGRN
			p.Name = d.Name
			p.EntityType = typ
			p.RegistrationStatus = d.Status
			p.ActualAt = d.CheckedAt
		}
		for field, value := range map[string]string{"inn": d.INN, "ogrn": d.OGRN, "name": d.Name, "registration_status": d.Status, "entity_type": typ} {
			if value != "" {
				p.FieldSources[field] = append(p.FieldSources[field], FieldSource{Provider: "DADATA", ActualAt: d.CheckedAt, Value: value})
			}
		}
	}
	for field, values := range p.FieldSources {
		if len(values) < 2 {
			continue
		}
		unique := map[string]bool{}
		for _, v := range values {
			value := strings.ToUpper(strings.TrimSpace(v.Value))
			if value != "UNKNOWN" {
				unique[value] = true
			}
		}
		if len(unique) > 1 {
			p.Conflicts = append(p.Conflicts, Conflict{Field: field, Values: values})
		}
	}
	for _, r := range risks {
		if r.SubjectINN == p.INN {
			p.RiskSignals = append(p.RiskSignals, r)
		}
	}
	if p.Status == "NOT_FOUND" && len(p.RiskSignals) > 0 {
		p.Status = "UNKNOWN"
	}
	return p
}
