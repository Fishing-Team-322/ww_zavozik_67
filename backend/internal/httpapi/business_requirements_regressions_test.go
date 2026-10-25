package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/google/uuid"
	"math"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync/atomic"
	"testing"
)

type tzRentML struct{ auditFlatML }

func (tzRentML) Forecast(ctx context.Context, r forecast.StochasticRequest) (forecast.StochasticForecast, error) {
	f, e := (auditFlatML{}).Forecast(ctx, r)
	for p := range f.Outflow {
		for d, dt := range f.Dates {
			if dt.Format("2006-01-02") == "2026-10-26" {
				f.Outflow[p][d] = 1000
			}
		}
	}
	return f, e
}
func TestTZAuditDetectedRentMustAffectForecast(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	s.ML = tzRentML{}
	base := "/v1/companies/" + cid
	pattern := auditCall(t, h, token, "POST", base+"/recurring", product.Doc{"title": "Rent", "direction": "out", "amount": 1000, "period": "monthly", "day_of_month": 26, "counterparty_name": "Landlord", "category": "rent", "confirmed": true}, 201)
	_, e := h.db.Pool.Exec(context.Background(), `UPDATE recurring_patterns SET extra=extra||'{"origin":"detected","baseline_amount":1000}'::jsonb WHERE id=$1`, pattern["id"])
	if e != nil {
		t.Fatal(e)
	}
	before := auditForecast(t, h, token, cid)
	auditCall(t, h, token, "PATCH", "/v1/recurring/"+pattern["id"].(string), product.Doc{"amount": 2000}, 200)
	after := auditForecast(t, h, token, cid)
	var calendarAmount float64
	e = h.db.Pool.QueryRow(context.Background(), `SELECT amount::float8 FROM planned_events WHERE company_id=$1 AND extra->>'recurring_id'=$2 AND event_date='2026-10-26'`, cid, pattern["id"]).Scan(&calendarAmount)
	if e != nil {
		t.Fatal(e)
	}
	old := before["points"].([]any)[29].(map[string]any)["p50"].(float64)
	now := after["points"].([]any)[29].(map[string]any)["p50"].(float64)
	if calendarAmount != 2000 {
		t.Fatal("fixture did not update calendar", calendarAmount)
	}
	if math.Abs((old-now)-1000) > .011 {
		t.Errorf("rent changed 1000 -> 2000, forecast change %.2f, want 1000", old-now)
	}
	// A second edit replaces the last confirmed amount, preserving the original
	// model estimate. Moving one occurrence affects its date, not its total.
	auditCall(t, h, token, "PATCH", "/v1/recurring/"+pattern["id"].(string), product.Doc{"amount": 500}, 200)
	decreased := auditForecast(t, h, token, cid)
	if got := decreased["points"].([]any)[29].(map[string]any)["p50"].(float64); math.Abs(got-old-500) > .011 {
		t.Fatal("repeated rent edit lost baseline", got, old)
	}
	var eventID string
	if err := h.db.Pool.QueryRow(context.Background(), `SELECT id::text FROM planned_events WHERE company_id=$1 AND extra->>'recurring_id'=$2 AND event_date='2026-10-26'`, cid, pattern["id"]).Scan(&eventID); err != nil {
		t.Fatal(err)
	}
	auditCall(t, h, token, "PATCH", "/v1/events/"+eventID, product.Doc{"date": "2026-10-29"}, 200)
	moved := auditForecast(t, h, token, cid)
	points := moved["points"].([]any)
	opening := moved["opening_balance"].(float64)
	if points[2].(map[string]any)["p50"] != opening || points[5].(map[string]any)["p50"] != opening-500 {
		t.Fatal("individual rent date did not replace model date", points[2], points[5])
	}
	comparison := auditCall(t, h, token, "POST", base+"/scenarios/preview", product.Doc{"steps": []product.Doc{{"kind": "scale_revenue", "factor": 2}}}, 200)
	scenario := comparison["scenario"].(map[string]any)["points"].([]any)
	if scenario[29].(map[string]any)["p50"] != points[29].(map[string]any)["p50"] {
		t.Fatal("expense reversal was incorrectly scaled as revenue")
	}
}
func tzAuditSource(t *testing.T, h *harness, s *product.Service, token, cid, kind string, feed func() product.Doc) func() {
	t.Helper()
	base := "/v1/companies/" + cid
	auditCall(t, h, token, "PATCH", base, product.Doc{"inn": "7707083893"}, 200)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(feed())
	}))
	t.Cleanup(server.Close)
	u, _ := url.Parse(server.URL)
	s.AllowedSourceHosts = append(s.AllowedSourceHosts, u.Host)
	s.EncryptionKey = bytes.Repeat([]byte("a"), 32)
	source := auditCall(t, h, token, "POST", base+"/sources", product.Doc{"kind": kind, "title": "TZ diagnostic source", "config": product.Doc{"url": server.URL, "token": "diagnostic-reader-token"}}, 201)
	return func() {
		t.Helper()
		j := auditCall(t, h, token, "POST", "/v1/sources/"+source["id"].(string)+"/sync", nil, 202)
		drainCase(t, s)
		got := auditCall(t, h, token, "GET", "/v1/jobs/"+j["id"].(string), nil, 200)
		if got["status"] != "done" {
			t.Fatal(got)
		}
	}
}
func TestTZAuditInvoiceAndPendingBankOrderMustNotDoubleCount(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "INV-42", "direction": "received", "amount": 1000, "issued_at": "2026-10-23", "due_at": "2026-10-26", "counterparty_name": "Supplier"}, 201)
	sync := tzAuditSource(t, h, s, token, cid, "bank_api", func() product.Doc {
		return product.Doc{"company_inn": "7707083893", "as_of": "2026-10-23", "complete": true, "items": []any{product.Doc{"external_id": "bank-order-42", "kind": "payment_order", "title": "Payment for invoice INV-42", "due_date": "2026-10-26", "amount_kopecks": 100000, "direction": "out", "status": "expected", "counterparty_name": "Supplier"}}}
	})
	sync()
	out := auditForecast(t, h, token, cid)
	last := out["points"].([]any)[29].(map[string]any)["p50"].(float64)
	expense := out["opening_balance"].(float64) - last
	if math.Abs(expense-1000) > .011 {
		t.Errorf("invoice and payment order counted twice: expense %.2f, want 1000", expense)
	}
	r := h.call("GET", base+"/events?from=2026-10-26&to=2026-10-26", "", token)
	status(t, r, 200)
	rows := decode[[]product.Doc](t, r)
	if len(rows) != 2 {
		t.Fatal("both source records must stay visible", rows)
	}
	var canonical, alias product.Doc
	for _, row := range rows {
		if row["source"] == "bank_api" {
			alias = row
		} else {
			canonical = row
		}
	}
	if alias["status"] != "linked" || alias["linked_event_id"] != canonical["id"] || len(canonical["linked_sources"].([]any)) != 1 {
		t.Fatal("missing provenance", rows)
	}
	r = h.call("GET", base+"/plan-fact?from=2026-10-26&to=2026-10-26", "", token)
	status(t, r, 200)
	if points := decode[[]product.Doc](t, r); points[0]["plan_out"] != float64(1000) {
		t.Fatal("plan-fact counted alias", points)
	}
}
func TestTZAuditVATOutstandingAfterPaidInstallment(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	remaining := atomic.Int64{}
	remaining.Store(10001)
	sync := tzAuditSource(t, h, s, token, cid, "tax_api", func() product.Doc {
		return product.Doc{"company_inn": "7707083893", "as_of": "2026-10-24", "complete": true, "items": []any{product.Doc{"external_id": "vat-q3", "kind": "tax", "title": "VAT Q3", "tax_kind": "vat", "period": "q3", "year": 2026, "amount_kopecks": remaining.Load(), "direction": "out", "status": "expected"}}}
	})
	sync()
	before := auditForecast(t, h, token, cid)
	_, e := h.db.Pool.Exec(context.Background(), `INSERT INTO operations(id,company_id,op_date,amount,direction,counterparty_name,purpose,balance_eod,category,category_method,dedup_hash) VALUES($1,$2,'2026-10-24',33.34,'out','FNS','First VAT installment',$3,'tax','rule',$1)`, uuid.NewString(), cid, before["opening_balance"].(float64)-33.34)
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.DB.ProductJob(context.Background(), tokenUserID(t, h, token), cid, "recompute", product.Doc{})
	if e != nil {
		t.Fatal(e)
	}
	drainCase(t, s)
	var paid int
	e = h.db.Pool.QueryRow(context.Background(), `SELECT count(*) FROM planned_events WHERE company_id=$1 AND source_kind='tax_api' AND status='received'`, cid).Scan(&paid)
	if e != nil || paid != 1 {
		t.Fatal("fixture did not reconcile first installment", paid, e)
	}
	remaining.Store(6667)
	sync()
	sync() // Replaying the updated liability must preserve the same allocation.
	out := auditCall(t, h, token, "GET", "/v1/companies/"+cid+"/forecast?horizon=90", nil, 200)
	last := out["points"].([]any)[89].(map[string]any)["p50"].(float64)
	expense := out["opening_balance"].(float64) - last
	if math.Abs(expense-66.67) > .011 {
		t.Errorf("remaining VAT 66.67, forecast outstanding expense %.2f", expense)
	}
	// The second receipt has the same amount as the first one. It must settle
	// the unpaid part once, and replaying the now-stale total must not restore it.
	_, e = h.db.Pool.Exec(context.Background(), `INSERT INTO operations(id,company_id,op_date,amount,direction,counterparty_name,purpose,balance_eod,category,category_method,dedup_hash) VALUES($1,$2,'2026-11-25',33.34,'out','FNS','Second VAT installment',$3,'tax','rule',$1)`, uuid.NewString(), cid, out["opening_balance"].(float64)-33.34)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.DB.ProductJob(context.Background(), tokenUserID(t, h, token), cid, "recompute", product.Doc{}); e != nil {
		t.Fatal(e)
	}
	drainCase(t, s)
	sync()
	var unpaid float64
	if e = h.db.Pool.QueryRow(context.Background(), `SELECT COALESCE(sum(amount),0)::float8 FROM planned_events WHERE company_id=$1 AND source_kind='tax_api' AND status IN ('expected','missed')`, cid).Scan(&unpaid); e != nil {
		t.Fatal(e)
	}
	if unpaid != 33.33 {
		t.Fatal("stale snapshot redistributed a paid installment", unpaid)
	}
	remaining.Store(3333)
	sync()
	sync()
	if e = h.db.Pool.QueryRow(context.Background(), `SELECT count(*) FROM planned_events WHERE company_id=$1 AND source_kind='tax_api' AND status='received' AND amount=33.34`, cid).Scan(&paid); e != nil || paid != 2 {
		t.Fatal("tax sync rewrote paid history", paid, e)
	}
}

func TestLinkedOrderPaidBeforeInvoiceAndSourceRemoval(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	sync := tzAuditSource(t, h, s, token, cid, "bank_api", func() product.Doc {
		return product.Doc{"company_inn": "7707083893", "as_of": "2026-10-23", "complete": true, "items": []any{product.Doc{"external_id": "late-invoice-order", "kind": "payment_order", "title": "Payment for invoice LATE-42", "due_date": "2026-10-26", "amount_kopecks": 100000, "direction": "out", "status": "expected", "counterparty_name": "Supplier"}}}
	})
	sync()
	report := importAuditCSV(t, h, s, token, cid, "date;amount;direction;counterparty;purpose;balance;id\n2026-10-24;1000;out;Supplier;Invoice LATE-42;108000;late-order\n")
	invoice := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "LATE-42", "direction": "received", "amount": 1000, "issued_at": "2026-10-23", "due_at": "2026-10-26", "counterparty_name": "Supplier"}, 201)
	drainCase(t, s)
	got := businessInvoiceState(t, h, cid, invoice["id"].(string))
	if got["status"] != "paid" || got["paid_amount"] != float64(1000) {
		t.Fatal("late invoice did not adopt existing receipt", got)
	}
	sync()
	drainCase(t, s)
	out := auditForecast(t, h, token, cid)
	if out["points"].([]any)[29].(map[string]any)["p50"] != out["opening_balance"] {
		t.Fatal("paid invoice charged again", out)
	}
	var reservations int
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM operation_settlements WHERE company_id=$1 AND source_kind='invoice'", cid).Scan(&reservations); err != nil || reservations != 1 {
		t.Fatal("reservation not transferred exactly once", reservations, err)
	}
	auditCall(t, h, token, "DELETE", "/v1/sources/"+report["source_id"].(string), product.Doc{"keep_data": false}, 204)
	drainCase(t, s)
	got = businessInvoiceState(t, h, cid, invoice["id"].(string))
	if got["paid_amount"] != float64(0) {
		t.Fatal("removed bank receipt retained on invoice", got)
	}
	var stale int
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM planned_events WHERE company_id=$1 AND matched_operation_id IS NOT NULL", cid).Scan(&stale); err != nil || stale != 0 {
		t.Fatal("stale linked receipt", stale, err)
	}
	out = auditForecast(t, h, token, cid)
	if out["opening_balance"].(float64)-out["points"].([]any)[29].(map[string]any)["p50"].(float64) != 1000 {
		t.Fatal("source removal must reopen exactly one obligation")
	}
}

func TestPaymentOrderLinkRequiresUnambiguousReference(t *testing.T) {
	for _, kind := range []string{"no_reference", "wrong_party", "ambiguous", "explicit", "document_number", "deleted_invoice"} {
		t.Run(kind, func(t *testing.T) {
			h, s, token, cid := auditSetup(t)
			base := "/v1/companies/" + cid
			invoice := product.Doc{"number": "INV-42", "direction": "received", "amount": 1000, "issued_at": "2026-10-23", "due_at": "2026-10-26", "counterparty_name": "Supplier"}
			saved := auditCall(t, h, token, "POST", base+"/invoices", invoice, 201)
			order := product.Doc{"external_id": "order-42", "kind": "payment_order", "title": "Payment for invoice INV-42", "due_date": "2026-10-26", "amount_kopecks": 100000, "direction": "out", "status": "expected", "counterparty_name": "Supplier"}
			want := float64(1000)
			switch kind {
			case "no_reference":
				order["title"] = "Payment"
				want = 2000
			case "wrong_party":
				order["counterparty_name"] = "Another supplier"
				want = 2000
			case "ambiguous":
				auditCall(t, h, token, "POST", base+"/invoices", invoice, 201)
				want = 3000
			case "explicit":
				var id string
				if err := h.db.Pool.QueryRow(context.Background(), `SELECT id::text FROM planned_events WHERE company_id=$1 AND extra->>'document_id'=$2`, cid, saved["id"]).Scan(&id); err != nil {
					t.Fatal(err)
				}
				order["related_event_id"] = id
				order["title"] = "Payment"
			case "document_number":
				order["document_number"] = "INV-42"
				order["title"] = "Payment"
			}
			sync := tzAuditSource(t, h, s, token, cid, "bank_api", func() product.Doc {
				return product.Doc{"company_inn": "7707083893", "as_of": "2026-10-23", "complete": true, "items": []any{order}}
			})
			sync()
			if kind == "deleted_invoice" {
				auditCall(t, h, token, "DELETE", "/v1/invoices/"+saved["id"].(string), nil, 204)
			}
			out := auditForecast(t, h, token, cid)
			expense := out["opening_balance"].(float64) - out["points"].([]any)[29].(map[string]any)["p50"].(float64)
			if expense != want {
				t.Fatal("unsafe or missing payment order link", expense, want)
			}
		})
	}
}

func businessInvoiceState(t *testing.T, h *harness, cid, id string) product.Doc {
	t.Helper()
	var raw []byte
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT data FROM product_documents WHERE company_id=$1 AND id=$2 AND kind='invoice'", cid, id).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	var d product.Doc
	if err := json.Unmarshal(raw, &d); err != nil {
		t.Fatal(err)
	}
	return d
}

func TestLinkedPartialInvoiceReceiptSurvivesProjectionRebuild(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	invoice := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "PART-42", "direction": "received", "amount": 10000, "paid_amount": 4000, "issued_at": "2026-10-23", "due_at": "2026-10-26", "counterparty_name": "Supplier"}, 201)
	sync := tzAuditSource(t, h, s, token, cid, "bank_api", func() product.Doc {
		return product.Doc{"company_inn": "7707083893", "as_of": "2026-10-23", "complete": true, "items": []any{product.Doc{"external_id": "partial-order", "kind": "payment_order", "title": "Payment for invoice PART-42", "due_date": "2026-10-26", "amount_kopecks": 600000, "direction": "out", "status": "expected", "counterparty_name": "Supplier"}}}
	})
	sync()
	importAuditCSV(t, h, s, token, cid, "date;amount;direction;counterparty;purpose;balance;id\n2026-10-24;6000;out;Supplier;Invoice PART-42;103000;partial-order\n")
	got := auditCall(t, h, token, "PATCH", "/v1/invoices/"+invoice["id"].(string), product.Doc{"number": "PART-42 renamed"}, 200)
	if got["paid_amount"] != float64(10000) {
		t.Fatal("invoice not fully paid", got)
	}
	sync()
	out := auditForecast(t, h, token, cid)
	if out["points"].([]any)[29].(map[string]any)["p50"] != out["opening_balance"] {
		t.Fatal("paid residual order reopened after document edit")
	}
	r := h.call("GET", base+"/plan-fact?from=2026-10-26&to=2026-10-26", "", token)
	status(t, r, 200)
	if rows := decode[[]product.Doc](t, r); rows[0]["plan_out"] != float64(10000) {
		t.Fatal("rebuilt full invoice and residual order counted twice", rows)
	}
}

func TestLinkedOrderProvenanceSurvivesSourceDeletionWithDataKept(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "KEEP-42", "direction": "received", "amount": 1000, "issued_at": "2026-10-23", "due_at": "2026-10-26", "counterparty_name": "Supplier"}, 201)
	sync := tzAuditSource(t, h, s, token, cid, "bank_api", func() product.Doc {
		return product.Doc{"company_inn": "7707083893", "as_of": "2026-10-23", "complete": true, "items": []any{product.Doc{"external_id": "kept-order", "kind": "payment_order", "title": "Payment for invoice KEEP-42", "due_date": "2026-10-26", "amount_kopecks": 100000, "direction": "out", "status": "expected", "counterparty_name": "Supplier"}}}
	})
	sync()
	var sourceID string
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT id::text FROM sources WHERE company_id=$1 AND kind='bank_api'", cid).Scan(&sourceID); err != nil {
		t.Fatal(err)
	}
	auditCall(t, h, token, "DELETE", "/v1/sources/"+sourceID, product.Doc{"keep_data": true}, 204)
	r := h.call("GET", base+"/events?from=2026-10-26&to=2026-10-26", "", token)
	status(t, r, 200)
	rows := decode[[]product.Doc](t, r)
	if len(rows) != 2 {
		t.Fatal("kept source data lost", rows)
	}
	for _, row := range rows {
		if row["source"] == "bank_api" && row["status"] != "linked" {
			t.Fatal("kept order link lost", row)
		}
	}
}
