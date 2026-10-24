package httpapi_test

import (
	"context"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestInvoiceAmountEditDoesNotInventAnAdditionalPayment(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	inv := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/invoices", product.Doc{"number": "Paid", "direction": "issued", "amount": float64(10000), "issued_at": "2026-10-20", "due_at": "2026-10-24", "status": "paid"}, 201)
	// The editor sends the unchanged paid status together with its edited amount.
	edited := auditCall(t, h, token, "PATCH", "/v1/invoices/"+inv["id"].(string), product.Doc{"amount": float64(20000), "paid_amount": float64(10000), "status": "paid"}, 200)
	if edited["paid_amount"] != float64(10000) || edited["status"] != "partial" {
		t.Fatalf("editing total invented a payment: %v", edited)
	}
	corrected := auditCall(t, h, token, "PATCH", "/v1/invoices/"+inv["id"].(string), product.Doc{"paid_amount": float64(5000)}, 200)
	if corrected["paid_amount"] != float64(5000) {
		t.Fatalf("explicit partial-payment correction was ignored: %v", corrected)
	}
}
func TestContractReceiptSurvivesMetadataEdit(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	contract := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/contracts", product.Doc{"number": "Contract", "direction": "in", "total": float64(10000), "counterparty_name": "Contract client", "additional": true, "schedule": []product.Doc{{"date": "2026-10-24", "amount": float64(10000), "status": "expected"}}}, 201)
	auditOperation(t, h, cid, "2026-10-24", "Contract client", "", 10000, 119000)
	drainCase(t, s)
	list := h.call("GET", "/v1/companies/"+cid+"/contracts", "", token)
	status(t, list, 200)
	// List decoding is an array; inspect the canonical stored schedule as well.
	var received bool
	e := h.db.Pool.QueryRow(context.Background(), "SELECT data->'schedule'->0->>'status'='received' FROM product_documents WHERE id=$1", contract["id"]).Scan(&received)
	if e != nil {
		t.Fatal(e)
	}
	if !received {
		t.Error("bank settlement did not update the contract schedule")
	}
	edited := auditCall(t, h, token, "PATCH", "/v1/contracts/"+contract["id"].(string), product.Doc{"number": "Contract renamed"}, 200)
	if edited["schedule"].([]any)[0].(map[string]any)["status"] != "received" {
		t.Error("editing metadata reopened a bank-settled installment")
	}
	// A form opened before reconciliation can still contain "expected".
	stale := []product.Doc{{"date": "2026-10-24", "amount": float64(10000), "status": "expected"}}
	edited = auditCall(t, h, token, "PATCH", "/v1/contracts/"+contract["id"].(string), product.Doc{"number": "Another rename", "schedule": stale}, 200)
	if edited["schedule"].([]any)[0].(map[string]any)["status"] != "received" {
		t.Fatal("stale editor reopened a paid installment", edited)
	}
	auditCall(t, h, token, "PATCH", "/v1/contracts/"+contract["id"].(string), product.Doc{"total": float64(12000), "schedule": []product.Doc{{"date": "2026-10-24", "amount": float64(12000), "status": "expected"}}}, 409)
	auditCall(t, h, token, "PATCH", "/v1/contracts/"+contract["id"].(string), product.Doc{"total": 10000.01, "schedule": []product.Doc{{"date": "2026-10-24", "amount": 10000.01, "status": "expected"}}}, 409)
	auditCall(t, h, token, "PATCH", "/v1/contracts/"+contract["id"].(string), product.Doc{"total": float64(0), "schedule": []product.Doc{}}, 409)
}

func TestReconciliationPreservesOneKopeckDifference(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	event := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/events", product.Doc{"date": "2026-10-24", "title": "Exact cents", "amount": 1000.01, "direction": "in", "counterparty_name": "Cents client"}, 201)
	auditOperation(t, h, cid, "2026-10-24", "Cents client", "", 1000, 110000)
	drainCase(t, s)
	var state string
	if e := h.db.Pool.QueryRow(context.Background(), "SELECT status FROM planned_events WHERE id=$1", event["id"]).Scan(&state); e != nil {
		t.Fatal(e)
	}
	if state == "received" {
		t.Fatal("one kopeck short was accepted as a full payment")
	}
}
func TestScenarioMarkersFollowMovedAndScaledPlans(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	event := auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-10-25", "title": "Scenario client", "amount": float64(1000), "direction": "in", "additional": true}, 201)
	got := auditCall(t, h, token, "POST", base+"/scenarios/preview", product.Doc{"steps": []product.Doc{{"kind": "move_event", "event_id": event["id"], "date": "2026-10-28"}, {"kind": "scale_revenue", "factor": 0.5}}}, 200)
	markers := got["scenario"].(map[string]any)["markers"].([]any)
	if len(markers) != 1 {
		t.Fatal(markers)
	}
	marker := markers[0].(map[string]any)
	if marker["date"] != "2026-10-28" || marker["amount"] != float64(500) {
		t.Fatalf("chart marker describes the old plan: %v", marker)
	}
}
func TestContractRecognizesPaymentTwoWeeksLate(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	contract := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/contracts", product.Doc{"number": "Late contract", "direction": "in", "total": float64(10000), "counterparty_name": "Late contract client", "additional": true, "schedule": []product.Doc{{"date": "2026-10-10", "amount": float64(10000), "status": "expected"}}}, 201)
	auditOperation(t, h, cid, "2026-10-24", "Late contract client", "", 10000, 119000)
	drainCase(t, s)
	var state string
	if e := h.db.Pool.QueryRow(context.Background(), "SELECT data->'schedule'->0->>'status' FROM product_documents WHERE id=$1", contract["id"]).Scan(&state); e != nil {
		t.Fatal(e)
	}
	if state != "received" {
		t.Fatalf("a payment two weeks late was not reconciled: %s", state)
	}
}
