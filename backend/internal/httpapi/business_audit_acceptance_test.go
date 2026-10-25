package httpapi_test

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/migrations"
	"github.com/google/uuid"
)

func TestBusinessAuditStaleStatementBlocksSpending(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	_, err := h.db.Pool.Exec(context.Background(), "UPDATE operations SET op_date=op_date-30 WHERE company_id=$1", cid)
	if err != nil {
		t.Fatal(err)
	}
	f := auditForecast(t, h, token, cid)
	if f["spending_available"] != false || f["safe_to_spend"] != float64(0) || f["probability_reliable"] != false || f["status"] == "ok" {
		t.Fatal("stale history advertised actionable money", f)
	}
	if f["data_age_days"].(float64) < 30 || f["forecast_end"] == nil {
		t.Fatal(f)
	}
	d := auditCall(t, h, token, "GET", "/v1/companies/"+cid+"/dashboard", nil, 200)
	if d["safe_to_spend"] != float64(0) || d["status"] == "ok" {
		t.Fatal(d)
	}
}

func TestBusinessAuditPlanAbsentIsNotZero(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	r := h.call("GET", "/v1/companies/"+cid+"/plan-fact?from=2026-10-23&to=2026-10-23", "", token)
	status(t, r, 200)
	rows := decode[[]product.Doc](t, r)
	if len(rows) != 1 || rows[0]["plan_available"] != false || rows[0]["plan_in"] != nil || rows[0]["deviation"] != nil || rows[0]["fact_in"] == nil {
		t.Fatal(rows)
	}
}

func TestBusinessAuditExplicitInvoiceReplacesOnePayment(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	event := auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-10-26", "amount": 1000, "direction": "out", "title": "Planned repair", "counterparty_name": "Repair supplier", "additional": true}, 201)
	invoice := product.Doc{"number": "REPAIR-1", "direction": "received", "amount": 1500, "issued_at": "2026-10-24", "due_at": "2026-10-27", "counterparty_name": "Repair supplier", "additional": true, "replaces_event_id": event["id"]}
	created := auditCall(t, h, token, "POST", base+"/invoices", invoice, 201)
	f := auditForecast(t, h, token, cid)
	points := f["points"].([]any)
	if points[2].(map[string]any)["p50"] != f["opening_balance"].(float64) || points[3].(map[string]any)["p50"] != f["opening_balance"].(float64)-1500 {
		t.Fatal("payment counted twice or on the old date", points[:4])
	}
	auditCall(t, h, token, "PATCH", "/v1/events/"+event["id"].(string), product.Doc{"amount": 2000}, 409)
	auditCall(t, h, token, "DELETE", "/v1/events/"+event["id"].(string), nil, 409)
	invoice["number"] = "REPAIR-2"
	auditCall(t, h, token, "POST", base+"/invoices", invoice, 409)
	// A removed unpaid document restores its original calendar plan.
	auditCall(t, h, token, "DELETE", "/v1/invoices/"+created["id"].(string), nil, 204)
	f = auditForecast(t, h, token, cid)
	if f["points"].([]any)[2].(map[string]any)["p50"] != f["opening_balance"].(float64)-1000 {
		t.Fatal("unpaid original not restored", f)
	}
	// Receipts reserve the bank fact once and preserve paid provenance even if
	// the invoice is later removed.
	incoming := auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-10-24", "amount": 500, "direction": "in", "title": "Client promise", "counterparty_name": "Audit buyer", "additional": true}, 201)
	paid := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "PAID-1", "direction": "issued", "amount": 500, "issued_at": "2026-10-23", "due_at": "2026-10-24", "counterparty_name": "Audit buyer", "additional": true, "replaces_event_id": incoming["id"]}, 201)
	auditOperation(t, h, cid, "2026-10-24", "Audit buyer", "", 500, 100000)
	drainCase(t, s)
	var amount float64
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT (data->>'paid_amount')::float8 FROM product_documents WHERE id=$1", paid["id"]).Scan(&amount); err != nil || amount != 500 {
		t.Fatal(err, amount)
	}
	auditCall(t, h, token, "DELETE", "/v1/invoices/"+paid["id"].(string), nil, 204)
	var state string
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT status FROM planned_events WHERE id=$1", incoming["id"]).Scan(&state); err != nil || state != "received" {
		t.Fatal(err, state)
	}
}

func TestBusinessAuditPaidAlertRemovedFromDashboard(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "LATE-1", "direction": "issued", "amount": 500, "issued_at": "2026-10-20", "due_at": "2026-10-22", "counterparty_name": "Late buyer"}, 201)
	drainCase(t, s)
	auditOperation(t, h, cid, "2026-10-24", "Late buyer", "", 500, 100000)
	if err := s.DB.QueueRecompute(context.Background(), auditOwner(t, h, cid), cid); err != nil {
		t.Fatal(err)
	}
	drainCase(t, s)
	d := auditCall(t, h, token, "GET", base+"/dashboard", nil, 200)
	for _, value := range d["alerts"].([]any) {
		if value.(map[string]any)["kind"] == "missed_payment" {
			t.Fatal("paid invoice still advertised as overdue", d)
		}
	}
}

func TestBusinessAuditFrozenPlanCannotBeInventedRetrospectively(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	f := auditForecast(t, h, token, cid)
	date := f["points"].([]any)[5].(map[string]any)["date"].(string)
	// A saved forecast is a plan for subsequent dates, even if its expected
	// flow was exactly zero. Backdating its as_of is not enough to prove that
	// the forecast existed before an already observed day.
	_, err := h.db.Pool.Exec(context.Background(), "UPDATE forecast_runs SET created_at=$2::date-1 WHERE company_id=$1", cid, date)
	if err != nil {
		t.Fatal(err)
	}
	r := h.call("GET", fmt.Sprintf("/v1/companies/%s/plan-fact?from=%s&to=%s", cid, date, date), "", token)
	status(t, r, 200)
	rows := decode[[]product.Doc](t, r)
	if rows[0]["plan_available"] != true || rows[0]["plan_in"] != float64(0) {
		t.Fatal(rows)
	}
	_, err = h.db.Pool.Exec(context.Background(), "UPDATE forecast_runs SET created_at=$2::date+1 WHERE company_id=$1", cid, date)
	if err != nil {
		t.Fatal(err)
	}
	r = h.call("GET", fmt.Sprintf("/v1/companies/%s/plan-fact?from=%s&to=%s", cid, date, date), "", token)
	status(t, r, 200)
	if rows = decode[[]product.Doc](t, r); rows[0]["plan_available"] != false {
		t.Fatal(rows)
	}
}

func auditOwner(t *testing.T, h *harness, cid string) string {
	t.Helper()
	var uid string
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT user_id::text FROM memberships WHERE company_id=$1 AND role='owner' LIMIT 1", cid).Scan(&uid); err != nil {
		t.Fatal(err)
	}
	return uid
}

func TestBusinessAuditExpectedPayoutRequestIsIdempotent(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	body := product.Doc{"date": "2026-10-26", "amount": 12345, "direction": "in", "title": "Confirmed payout", "category": "revenue_marketplace", "source_ref": "wb report 123", "request_id": uuid.NewString(), "additional": true}
	first := auditCall(t, h, token, "POST", base+"/events", body, 201)
	again := auditCall(t, h, token, "POST", base+"/events", body, 201)
	if first["id"] != again["id"] || again["source_ref"] != "wb report 123" {
		t.Fatal(first, again)
	}
	body["amount"] = 12346
	auditCall(t, h, token, "POST", base+"/events", body, 409)
	var n int
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM planned_events WHERE company_id=$1", cid).Scan(&n); err != nil || n != 1 {
		t.Fatal(n, err)
	}
}

func TestBusinessAuditReplacementUsesINNAndRejectsSettledPayments(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	event := auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-10-26", "amount": 1000, "direction": "out", "title": "Repair", "counterparty_name": "Supplier short name", "counterparty_inn": "7707083893", "additional": true}, 201)
	invoice := product.Doc{"number": "INN-1", "direction": "received", "amount": 1500, "issued_at": "2026-10-24", "due_at": "2026-10-27", "counterparty_name": "Supplier full legal name", "counterparty_inn": "7707083894", "additional": true, "replaces_event_id": event["id"]}
	auditCall(t, h, token, "POST", base+"/invoices", invoice, 400)
	invoice["counterparty_inn"] = "7707083893"
	created := auditCall(t, h, token, "POST", base+"/invoices", invoice, 201)
	auditCall(t, h, token, "DELETE", "/v1/invoices/"+created["id"].(string), nil, 204)
	op := auditOperation(t, h, cid, "2026-10-24", "Supplier", "7707083893", 1000, 100000)
	// Legacy/manual state changes must not make an already matched bank fact
	// eligible for a second payable invoice.
	if _, err := h.db.Pool.Exec(context.Background(), "UPDATE planned_events SET status='expected',matched_operation_id=$2 WHERE id=$1", event["id"], op); err != nil {
		t.Fatal(err)
	}
	auditCall(t, h, token, "POST", base+"/invoices", invoice, 409)
}

func TestBusinessAuditMigrationPreservesUserCategories(t *testing.T) {
	h, _, _, cid := auditSetup(t)
	ctx := context.Background()
	automatic := auditOperation(t, h, cid, "2026-10-24", "Собственник", "", 1000, 100000)
	user := auditOperation(t, h, cid, "2026-10-24", "Учредитель", "", 1000, 101000)
	if _, err := h.db.Pool.Exec(ctx, "UPDATE operations SET category='other',purpose='Договор займа',category_method=CASE WHEN id=$1 THEN 'user' ELSE 'rule' END WHERE id IN ($1,$2)", user, automatic); err != nil {
		t.Fatal(err)
	}
	raw, err := migrations.Files.ReadFile("00012_business_audit.sql")
	if err != nil {
		t.Fatal(err)
	}
	up := strings.SplitN(string(raw), "-- +goose Down", 2)[0]
	if _, err = h.db.Pool.Exec(ctx, up); err != nil {
		t.Fatal(err)
	}
	for id, expected := range map[string]string{automatic: "owner_loan", user: "other"} {
		var category string
		if err = h.db.Pool.QueryRow(ctx, "SELECT category FROM operations WHERE id=$1", id).Scan(&category); err != nil || category != expected {
			t.Fatal("migration lost category provenance", category, expected, err)
		}
	}
	var before, after int64
	if err = h.db.Pool.QueryRow(ctx, "SELECT data_revision FROM companies WHERE id=$1", cid).Scan(&before); err != nil {
		t.Fatal(err)
	}
	if _, err = h.db.Pool.Exec(ctx, up); err != nil {
		t.Fatal(err)
	}
	if err = h.db.Pool.QueryRow(ctx, "SELECT data_revision FROM companies WHERE id=$1", cid).Scan(&after); err != nil || before != after {
		t.Fatal("migration is not idempotent", before, after, err)
	}
}
