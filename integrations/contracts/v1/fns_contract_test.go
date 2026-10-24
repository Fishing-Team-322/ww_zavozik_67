package v1

import (
	"encoding/json"
	"os"
	"testing"
)

func TestCounterpartyExampleAndSchema(t *testing.T) {
	b, e := os.ReadFile("counterparty-intelligence.schema.json")
	if e != nil {
		t.Fatal(e)
	}
	var schema map[string]any
	if e = json.Unmarshal(b, &schema); e != nil {
		t.Fatal(e)
	}
	b, e = os.ReadFile("example-counterparty-intelligence.json")
	if e != nil {
		t.Fatal(e)
	}
	var wrapper struct {
		CompanyID string `json:"company_id"`
		Profile   struct {
			INN          string         `json:"inn"`
			Status       string         `json:"status"`
			FieldSources map[string]any `json:"field_sources"`
			RiskSignals  []any          `json:"risk_signals"`
		} `json:"profile"`
	}
	if e = json.Unmarshal(b, &wrapper); e != nil {
		t.Fatal(e)
	}
	if wrapper.CompanyID == "" || wrapper.Profile.INN == "" || wrapper.Profile.Status == "" || wrapper.Profile.FieldSources == nil || wrapper.Profile.RiskSignals == nil {
		t.Fatalf("incomplete example: %+v", wrapper)
	}
	if schema["title"] == nil || schema["required"] == nil {
		t.Fatal("incomplete schema")
	}
}
