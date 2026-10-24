package httpapi_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func auditGapAction(t *testing.T, h *harness, token, cid, kind string, horizon int) (product.Doc, product.Doc) {
	t.Helper()
	base := "/v1/companies/" + cid
	query := fmt.Sprintf("?horizon=%d", horizon)
	forecast := auditCall(t, h, token, "GET", base+"/forecast"+query, nil, 200)
	gaps := forecast["gaps"].([]any)
	if len(gaps) == 0 {
		t.Fatal("fixture must have a gap")
	}
	gap := auditCall(t, h, token, "GET", base+"/gaps/"+gaps[0].(map[string]any)["id"].(string)+query, nil, 200)
	for _, raw := range gap["actions"].([]any) {
		a := product.Doc(raw.(map[string]any))
		if a["kind"] == kind {
			return a, gap
		}
	}
	t.Fatal("fixture action missing", kind)
	return nil, nil
}

func TestGapActionCannotApplyAfterFinancialDataChanges(t *testing.T) {
	for _, kind := range []string{"shift_supplier_payment", "overdraft"} {
		t.Run(kind, func(t *testing.T) {
			h, _, token, cid := auditSetup(t)
			event := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/events", product.Doc{"date": "2026-10-24", "title": "Gap expense", "amount": 200000, "direction": "out"}, 201)
			action, _ := auditGapAction(t, h, token, cid, kind, 30)
			change := product.Doc{"date": "2026-11-20"}
			if kind == "overdraft" {
				change = product.Doc{"amount": 1000}
			}
			auditCall(t, h, token, "PATCH", "/v1/events/"+event["id"].(string), change, 200)
			auditCall(t, h, token, "POST", "/v1/actions/"+action["id"].(string)+"/apply", nil, 409)
			if kind == "shift_supplier_payment" {
				fresh, _ := auditGapAction(t, h, token, cid, kind, 30)
				if fresh["id"] == action["id"] {
					t.Fatal("refresh reused the stale recommendation")
				}
				auditCall(t, h, token, "POST", "/v1/actions/"+fresh["id"].(string)+"/apply", nil, 200)
				var date string
				if err := h.db.Pool.QueryRow(context.Background(), "SELECT event_date::text FROM planned_events WHERE id=$1", event["id"]).Scan(&date); err != nil {
					t.Fatal(err)
				}
				if date != "2026-12-04" {
					t.Fatal("refreshed recommendation used old payment terms", date)
				}
			} else {
				var count int
				if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM planned_events WHERE company_id=$1 AND category='owner_loan'", cid).Scan(&count); err != nil {
					t.Fatal(err)
				}
				if count != 0 {
					t.Fatal("stale action created unnecessary funding", count)
				}
			}
		})
	}
}

func TestGapActionsForDifferentHorizonsKeepTheirOwnAmounts(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	for _, e := range []product.Doc{{"date": "2026-10-24", "title": "Early expense", "amount": 200000, "direction": "out"}, {"date": "2026-12-01", "title": "Later expense", "amount": 300000, "direction": "out"}} {
		auditCall(t, h, token, "POST", base+"/events", e, 201)
	}
	short, _ := auditGapAction(t, h, token, cid, "overdraft", 30)
	long, gap := auditGapAction(t, h, token, cid, "overdraft", 90)
	repeated, _ := auditGapAction(t, h, token, cid, "overdraft", 90)
	if repeated["id"] != long["id"] {
		t.Fatal("unchanged forecast changed its action IDs")
	}
	if short["id"] == long["id"] {
		t.Error("different forecast recommendations share one persisted action")
	}
	auditCall(t, h, token, "POST", "/v1/actions/"+long["id"].(string)+"/apply", nil, 200)
	var amount float64
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT amount::float8 FROM planned_events WHERE company_id=$1 AND category='owner_loan'", cid).Scan(&amount); err != nil {
		t.Fatal(err)
	}
	if amount != gap["shortfall_p90"] {
		t.Fatalf("applied another horizon's funding amount: got %v want %v", amount, gap["shortfall_p90"])
	}
	// A retry of an already applied action stays idempotent after the revision changes.
	auditCall(t, h, token, "POST", "/v1/actions/"+long["id"].(string)+"/apply", nil, 200)
}

func TestForecastPreviewCombinesEditsAndNewEvents(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	event := auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-10-24", "title": "Existing expense", "amount": 1000, "direction": "out"}, 201)
	preview := auditCall(t, h, token, "POST", base+"/forecast/preview", product.Doc{"changes": []product.Doc{{"id": event["id"], "amount": 2000}}, "events": []product.Doc{{"date": "2026-10-24", "title": "New expense", "amount": 3000, "direction": "out"}}}, 200)
	point := preview["forecast"].(map[string]any)["points"].([]any)[0].(map[string]any)
	if point["p50"] != float64(104000) {
		t.Fatal("one of the two preview input arrays was ignored", point)
	}
	// A preview must not apply either change to the real plans.
	actual := auditForecast(t, h, token, cid)["points"].([]any)[0].(map[string]any)
	if actual["p50"] != float64(108000) {
		t.Fatal("preview changed real plans", actual)
	}
}

func TestForecastPreviewRejectsNullArrayEntries(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	for _, body := range []string{`{"changes":[null]}`, `{"events":[null]}`} {
		status(t, h.call("POST", "/v1/companies/"+cid+"/forecast/preview", body, token), 400)
	}
}
