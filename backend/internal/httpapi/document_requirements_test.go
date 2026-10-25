package httpapi_test

import (
	"math"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestDocumentsAffectForecastByDefault(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	before := auditForecast(t, h, token, cid)
	invoice := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "Expected receipt", "direction": "issued", "amount": 1000, "issued_at": "2026-10-23", "due_at": "2026-10-26"}, 201)
	if invoice["additional"] != true {
		t.Fatal("new invoice must explicitly participate in forecast", invoice)
	}
	assertDelta := func(want float64) {
		t.Helper()
		got := auditForecast(t, h, token, cid)
		old, next := before["points"].([]any), got["points"].([]any)
		for i := range next {
			p, q := old[i].(map[string]any), next[i].(map[string]any)
			delta := 0.0
			if q["date"].(string) >= "2026-10-26" {
				delta = want
			}
			if math.Abs(q["p50"].(float64)-p["p50"].(float64)-delta) > .011 {
				t.Fatal("document changes cash on the wrong date or more than once", p, q, delta)
			}
		}
	}
	assertDelta(1000)
	assertDelta(1000)
	auditCall(t, h, token, "PATCH", "/v1/invoices/"+invoice["id"].(string), product.Doc{"paid_amount": 400}, 200)
	assertDelta(600)
	auditCall(t, h, token, "PATCH", "/v1/invoices/"+invoice["id"].(string), product.Doc{"status": "paid"}, 200)
	assertDelta(0)
	// Explicitly base-covered documents are still supported and exposed.
	covered := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "Already in baseline", "direction": "received", "amount": 2000, "issued_at": "2026-10-23", "due_at": "2026-10-26", "additional": false}, 201)
	if covered["additional"] != false {
		t.Fatal(covered)
	}
	assertDelta(0)
}

func TestContractTermsProducePrepaymentAndDeferredBalance(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	contract := auditCall(t, h, token, "POST", base+"/contracts", product.Doc{"number": "Equipment", "direction": "out", "total": 10000, "prepayment": 3000, "deferral_days": 14, "start_date": "2026-10-26"}, 201)
	if contract["additional"] != true || contract["schedule_mode"] != "terms" {
		t.Fatal(contract)
	}
	schedule := contract["schedule"].([]any)
	if len(schedule) != 2 || schedule[0].(map[string]any)["date"] != "2026-10-26" || schedule[1].(map[string]any)["date"] != "2026-11-09" || schedule[1].(map[string]any)["amount"] != float64(7000) {
		t.Fatal("wrong prepayment or deferral", schedule)
	}
	check := func() {
		t.Helper()
		out := auditForecast(t, h, token, cid)
		opening := out["opening_balance"].(float64)
		for _, v := range out["points"].([]any) {
			p := v.(map[string]any)
			want := opening
			if p["date"].(string) >= "2026-10-26" {
				want -= 3000
			}
			if p["date"].(string) >= "2026-11-09" {
				want -= 7000
			}
			if math.Abs(p["p50"].(float64)-want) > .011 {
				t.Fatal(p, want)
			}
		}
	}
	check()
	auditCall(t, h, token, "PATCH", "/v1/contracts/"+contract["id"].(string), product.Doc{"number": "Equipment renamed"}, 200)
	check()
	auditCall(t, h, token, "POST", base+"/contracts", product.Doc{"number": "No dates", "direction": "out", "total": 10000}, 400)
	// Metadata updates must not reopen a manually paid auto-generated installment.
	schedule[0].(map[string]any)["status"] = "received"
	auditCall(t, h, token, "PATCH", "/v1/contracts/"+contract["id"].(string), product.Doc{"schedule": schedule}, 200)
	updated := auditCall(t, h, token, "PATCH", "/v1/contracts/"+contract["id"].(string), product.Doc{"number": "Paid advance"}, 200)
	if updated["schedule"].([]any)[0].(map[string]any)["status"] != "received" {
		t.Fatal(updated)
	}
}
