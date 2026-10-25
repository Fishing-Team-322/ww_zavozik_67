package httpapi_test

import (
	"context"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestRiskDatesStayConsistentAcrossForecastOverviewDetailAndSimulation(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	s.Now = func() time.Time { return time.Date(2026, 10, 25, 23, 0, 0, 0, time.UTC) }
	if _, err := h.db.Pool.Exec(context.Background(), "UPDATE operations SET op_date=op_date-24 WHERE company_id=$1", cid); err != nil {
		t.Fatal(err)
	}
	base := "/v1/companies/" + cid
	var smallPaymentID string
	for _, event := range []product.Doc{
		{"title": "Small movable payment", "date": "2026-10-26", "amount": 1000, "direction": "out", "additional": true},
		{"title": "First risk payment", "date": "2026-10-27", "amount": 500000, "direction": "out", "additional": true},
		{"title": "Later worst-day payment", "date": "2026-10-28", "amount": 5000, "direction": "out", "additional": true},
	} {
		created := auditCall(t, h, token, "POST", base+"/events", event, 201)
		if event["title"] == "Small movable payment" {
			smallPaymentID = created["id"].(string)
		}
	}
	check := func(label string, gap map[string]any) {
		t.Helper()
		if gap["date"] != "2026-10-27" || gap["days_left"] != float64(2) || gap["worst_date"] != "2026-10-28" {
			t.Fatalf("%s: wrong risk dates: %s", label, mustAuditJSON(gap))
		}
		if gap["explanation"].(map[string]any)["date"] != "2026-10-28" {
			t.Fatal("wrong explanation date", gap)
		}
	}
	fc := auditForecast(t, h, token, cid)
	if fc["as_of"] != "2026-09-29" {
		t.Fatal("fixture must contain a stale statement", fc["as_of"])
	}
	gap := fc["gaps"].([]any)[0].(map[string]any)
	check("forecast", gap)
	check("overview", auditCall(t, h, token, "GET", base+"/dashboard", nil, 200)["top_gap"].(map[string]any))
	detail := auditCall(t, h, token, "GET", base+"/gaps/"+gap["id"].(string), nil, 200)
	check("detail", detail)
	var actionID string
	for _, raw := range detail["actions"].([]any) {
		action := raw.(map[string]any)
		if action["kind"] == "shift_supplier_payment" && action["refs"].(map[string]any)["event_id"] == smallPaymentID {
			actionID = action["id"].(string)
			break
		}
	}
	if actionID == "" {
		t.Fatal("fixture must offer a payment shift")
	}
	simulated := auditCall(t, h, token, "POST", base+"/gaps/"+gap["id"].(string)+"/simulate", product.Doc{"action_ids": []string{actionID}}, 200)
	simulatedGaps := simulated["gaps"].([]any)
	if len(simulatedGaps) != 1 {
		t.Fatal("moving the small payment must keep the later risk", simulated)
	}
	check("simulation", simulatedGaps[0].(map[string]any))
}
