package httpapi_test

import (
	"context"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestCashflowReceiptSuggestionSimulateAndApplyInvoice(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-10-24", "title": "Equipment", "amount": 200000, "direction": "out", "additional": true}, 201)
	invoice := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "RECEIPT-SUGGESTION", "direction": "issued", "amount": 150000, "issued_at": "2026-10-23", "due_at": "2026-10-30", "counterparty_name": "Synthetic buyer", "additional": true}, 201)
	action, gap := auditGapAction(t, h, token, cid, "accelerate_receivable", 30)
	effect := action["effect"].(map[string]any)
	if effect["baseline_shortfall"] != float64(91000) || effect["new_shortfall"] != float64(0) || effect["shortfall_reduction"] != float64(91000) || action["draft_message"] == nil || action["conditions"] == nil {
		t.Fatal(action)
	}
	if action["explanation_source"] != "rules" {
		t.Fatal("default needs no external API", action)
	}
	var before, after int
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM operations WHERE company_id=$1", cid).Scan(&before); err != nil {
		t.Fatal(err)
	}
	simulated := auditCall(t, h, token, "POST", base+"/gaps/"+gap["id"].(string)+"/simulate", product.Doc{"action_ids": []string{action["id"].(string)}}, 200)
	if len(simulated["gaps"].([]any)) != 0 {
		t.Fatal("simulation disagrees with suggestion", simulated)
	}
	unchanged := cashflowInvoice(t, h, cid, invoice["id"].(string))
	if unchanged["expected_pay_at"] != "2026-10-30" {
		t.Fatal("preview changed document", unchanged)
	}
	auditCall(t, h, token, "POST", "/v1/actions/"+action["id"].(string)+"/apply", nil, 200)
	drainCase(t, s)
	updated := cashflowInvoice(t, h, cid, invoice["id"].(string))
	if updated["expected_pay_at"] != "2026-10-24" || updated["due_at"] != "2026-10-30" {
		t.Fatal("document expectation not synchronized", updated)
	}
	actual := auditForecast(t, h, token, cid)
	if len(actual["gaps"].([]any)) != 0 || actual["points"].([]any)[0].(map[string]any)["p50"] != simulated["points"].([]any)[0].(map[string]any)["p50"] {
		t.Fatal("applied plan differs from simulated effect", actual)
	}
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM operations WHERE company_id=$1", cid).Scan(&after); err != nil || after != before {
		t.Fatal("recommendation created bank facts", err, before, after)
	}
	auditCall(t, h, token, "POST", "/v1/actions/"+action["id"].(string)+"/apply", nil, 200)
}

func TestCashflowSupplierInvoiceSuggestionKeepsSourceDate(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	invoice := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/invoices", product.Doc{"number": "SUPPLIER-SUGGESTION", "direction": "received", "amount": 200000, "issued_at": "2026-10-23", "due_at": "2026-10-24", "counterparty_name": "Synthetic supplier", "additional": true}, 201)
	action, _ := auditGapAction(t, h, token, cid, "shift_supplier_payment", 30)
	auditCall(t, h, token, "POST", "/v1/actions/"+action["id"].(string)+"/apply", nil, 200)
	drainCase(t, s)
	updated := cashflowInvoice(t, h, cid, invoice["id"].(string))
	if updated["expected_pay_at"] != "2026-11-07" || updated["due_at"] != "2026-10-24" {
		t.Fatal(updated)
	}
	var date string
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT event_date::text FROM planned_events WHERE company_id=$1 AND extra->>'document_id'=$2", cid, invoice["id"]).Scan(&date); err != nil || date != "2026-11-07" {
		t.Fatal("reconciliation restored old invoice date", err, date)
	}
}

func cashflowInvoice(t *testing.T, h *harness, cid, id string) product.Doc {
	t.Helper()
	var uid string
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT user_id::text FROM memberships WHERE company_id=$1 AND role='owner' LIMIT 1", cid).Scan(&uid); err != nil {
		t.Fatal(err)
	}
	doc, err := h.db.ProductGet(context.Background(), uid, "invoice", id)
	if err != nil {
		t.Fatal(err)
	}
	return doc
}
