package httpapi_test

import (
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestScenarioWindowRetainsEarlierFlowsAndExcludesLaterRisk(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-10-25", "title": "Expense before window", "direction": "out", "amount": 200000, "additional": true}, 201)
	auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-12-02", "title": "Expense after window", "direction": "out", "amount": 500000, "additional": true}, 201)
	query := "?from=2026-11-02&to=2026-12-01"
	steps := []product.Doc{{"kind": "add_expense", "amount": 1000, "date": "2026-10-26"}}
	comparison := auditCall(t, h, token, "POST", base+"/scenarios/preview"+query, product.Doc{"steps": steps}, 200)
	check := func(comparison product.Doc) {
		t.Helper()
		b, s := comparison["base"].(map[string]any), comparison["scenario"].(map[string]any)
		bp, sp := b["points"].([]any), s["points"].([]any)
		if len(bp) != 30 || len(sp) != 30 || b["as_of"] != "2026-10-23" || bp[0].(map[string]any)["date"] != "2026-11-02" || bp[29].(map[string]any)["date"] != "2026-12-01" {
			t.Fatal("window shifted the statement or returned wrong dates", b)
		}
		want := b["opening_balance"].(float64) - 200000
		for i := range bp {
			if bp[i].(map[string]any)["p50"] != want || sp[i].(map[string]any)["p50"] != want-1000 {
				t.Fatal("window erased earlier cash flows or included a later expense", bp[i], sp[i])
			}
		}
		gap := s["gaps"].([]any)[0].(map[string]any)
		if gap["date"] != "2026-11-02" || gap["shortfall"] != -want+1000 || gap["probability"] != float64(1) {
			t.Fatal("risk and minimum must use the same window as the chart", gap)
		}
		if gap["explanation"].(map[string]any)["balance"] != want-1000 {
			t.Fatal("explanation lost cumulative flows", gap)
		}
	}
	check(comparison)
	saved := auditCall(t, h, token, "POST", base+"/scenarios", product.Doc{"title": "Stored window scenario", "steps": steps}, 201)
	check(auditCall(t, h, token, "GET", "/v1/scenarios/"+saved["id"].(string)+"/compare"+query, nil, 200))
	late := auditCall(t, h, token, "POST", base+"/scenarios/preview"+query, product.Doc{"steps": []product.Doc{{"kind": "add_expense", "amount": 999999, "date": "2026-12-02"}}}, 200)
	if late["delta"].(map[string]any)["min_balance"] != float64(0) {
		t.Fatal("expense after the selected end changed its statistics", late)
	}
	for _, query := range []string{
		"?from=2026-10-23&to=2026-11-21",
		"?from=2026-12-24&to=2027-01-22",
		"?from=2026-11-02&to=2026-12-02",
		"?from=2026-11-02",
	} {
		auditCall(t, h, token, "POST", base+"/scenarios/preview"+query, product.Doc{"steps": steps}, 400)
	}
	// Both exact horizon boundaries are supported.
	for _, query := range []string{"?from=2026-10-24&to=2026-11-22", "?from=2026-12-23&to=2027-01-21"} {
		auditCall(t, h, token, "POST", base+"/scenarios/preview"+query, product.Doc{"steps": steps}, 200)
	}
}
