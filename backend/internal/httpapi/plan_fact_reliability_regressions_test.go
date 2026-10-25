package httpapi_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestPlanFactSavedRiskDoesNotExposeLimitedOrBelowThresholdPercentages(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	ctx := context.Background()
	for _, item := range []struct {
		revision int
		payload  product.Doc
	}{
		{100, product.Doc{"as_of": "2026-10-23", "probability_reliable": true, "gaps": []product.Doc{}}},
		{101, product.Doc{"as_of": "2026-10-23", "low_confidence": true, "probability_reliable": true, "gaps": []product.Doc{{"date": "2026-11-01", "probability": 1.0}}}},
	} {
		raw, _ := json.Marshal(item.payload)
		_, err := h.db.Pool.Exec(ctx, `INSERT INTO forecast_runs(company_id,as_of,horizon,model_used,opening_balance,safe_to_spend,revision,payload) VALUES($1,'2026-10-23',30,'structural_m6',100000,0,$2,$3)`, cid, item.revision, raw)
		if err != nil {
			t.Fatal(err)
		}
	}
	change := auditCall(t, h, token, "GET", "/v1/companies/"+cid+"/plan-fact/missed", nil, 200)["forecast_change"].(map[string]any)
	if change["probability_before"] != nil || change["probability_after"] != nil || change["probability_reliable_before"] != false || change["probability_reliable_after"] != false {
		t.Fatal("plan-fact advertised 0%/100% from limited snapshots", change)
	}
	if change["revision_before"] != float64(100) || change["revision_after"] != float64(101) || change["gap_date"] != "2026-11-01" {
		t.Fatal("risk dates and audit revisions must remain visible", change)
	}
}

func TestScenariosRequireCompanyHistoryAndDoNotBorrowAnotherCompanysData(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	other := auditCall(t, h, token, "POST", "/v1/companies", product.Doc{"name": "Empty scenario tenant", "legal_form": "ООО", "industry": "services"}, 201)["id"].(string)
	steps := product.Doc{"steps": []product.Doc{{"kind": "add_expense", "amount": 1234.56, "date": "2026-10-26"}}}
	r := h.call("POST", "/v1/companies/"+other+"/scenarios/preview", `{"steps":[{"kind":"scale_revenue","factor":0.8}]}`, token)
	status(t, r, 422)
	if decode[product.Doc](t, r)["code"] != "data_required" {
		t.Fatal("empty company must request its own history", r.Body)
	}
	base := "/v1/companies/" + cid
	before := auditForecast(t, h, token, cid)
	events := h.call("GET", base+"/events", "", token).Body.String()
	comparison := auditCall(t, h, token, "POST", base+"/scenarios/preview", steps, 200)
	b := comparison["base"].(map[string]any)
	s := comparison["scenario"].(map[string]any)
	if b["opening_balance"] != before["opening_balance"] || s["opening_balance"] != before["opening_balance"] {
		t.Fatal("scenario did not use the company's imported closing balance", comparison)
	}
	for i, point := range s["points"].([]any) {
		original := b["points"].([]any)[i].(map[string]any)
		changed := point.(map[string]any)
		want := original["p50"].(float64)
		if changed["date"].(string) >= "2026-10-26" {
			want -= 1234.56
		}
		if diff := changed["p50"].(float64) - want; diff < -.011 || diff > .011 {
			t.Fatal("scenario expense not recomputed on actual paths", original, changed)
		}
	}
	if h.call("GET", base+"/events", "", token).Body.String() != events {
		t.Fatal("preview changed company plans")
	}
}
