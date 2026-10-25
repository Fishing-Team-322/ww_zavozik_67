package httpapi_test

import (
	"context"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/migrations"
	"github.com/google/uuid"
)

func TestPlanFactRetainsFullInvoicePlanAfterPartialPayment(t *testing.T) {
	for _, direction := range []string{"issued", "received"} {
		t.Run(direction, func(t *testing.T) {
			h, _, token, cid := auditSetup(t)
			base := "/v1/companies/" + cid
			inv := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "Partial plan", "direction": direction, "amount": 10000, "paid_amount": 4000, "issued_at": "2026-10-20", "due_at": "2026-10-23"}, 201)
			calendar := h.call("GET", base+"/events?from=2026-10-23&to=2026-10-23", "", token)
			status(t, calendar, 200)
			if rows := decode[[]product.Doc](t, calendar); len(rows) != 1 || rows[0]["amount"] != float64(6000) {
				t.Fatal("calendar must retain only the unpaid amount", rows)
			}
			check := func() {
				t.Helper()
				r := h.call("GET", base+"/plan-fact?from=2026-10-23&to=2026-10-23", "", token)
				status(t, r, 200)
				rows := decode[[]product.Doc](t, r)
				field := "plan_in"
				if direction == "received" {
					field = "plan_out"
				}
				if len(rows) != 1 || rows[0][field] != float64(10000) {
					t.Errorf("partial payment rewrote the original plan: %v", rows)
				}
				// Recording payment on a document must not create bank facts.
				if rows[0]["fact_in"] != float64(500) || rows[0]["fact_out"] != float64(400) {
					t.Fatal("document payment invented cash movements", rows)
				}
			}
			check()
			auditCall(t, h, token, "PATCH", "/v1/invoices/"+inv["id"].(string), product.Doc{"status": "paid"}, 200)
			check()
		})
	}
}

func TestUnconfirmedRecurringDoesNotCompeteWithInvoice(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	p := auditCall(t, h, token, "POST", base+"/recurring", product.Doc{"title": "Candidate", "direction": "in", "amount": 10000, "period": "monthly", "day_of_month": 24, "counterparty_name": "Candidate client", "confirmed": false}, 201)
	r := h.call("GET", base+"/events?from=2026-10-24&to=2026-10-24", "", token)
	status(t, r, 200)
	if rows := decode[[]product.Doc](t, r); len(rows) != 0 {
		t.Errorf("unconfirmed pattern created obligations: %v", rows)
	}
	inv := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "Real invoice", "direction": "issued", "amount": 10000, "issued_at": "2026-10-20", "due_at": "2026-10-24", "counterparty_name": "Candidate client"}, 201)
	auditOperation(t, h, cid, "2026-10-24", "Candidate client", "", 10000, 119000)
	drainCase(t, s)
	var paid float64
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT (data->>'paid_amount')::float8 FROM product_documents WHERE id=$1", inv["id"]).Scan(&paid); err != nil {
		t.Fatal(err)
	}
	if paid != 10000 {
		t.Error("unconfirmed pattern blocked bank settlement of a real invoice", paid)
	}
	// Confirmation must still enable normal projection.
	auditCall(t, h, token, "PATCH", "/v1/recurring/"+p["id"].(string), product.Doc{"confirmed": true}, 200)
	r = h.call("GET", base+"/events?from=2026-10-24&to=2026-10-24", "", token)
	status(t, r, 200)
	if rows := decode[[]product.Doc](t, r); len(rows) != 2 {
		t.Fatal("confirmed pattern was not projected", rows)
	}
}

func TestUnexpectedPaymentsExcludeInternalAndDuplicateFacts(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	ctx := context.Background()
	internal := auditOperation(t, h, cid, "2026-10-24", "Own account", "", 1000, 112000)
	duplicate := auditOperation(t, h, cid, "2026-10-24", "Duplicate", "", 1000, 112000)
	external := auditOperation(t, h, cid, "2026-10-24", "Actual client", "", 1000, 112000)
	if _, err := h.db.Pool.Exec(ctx, "UPDATE operations SET is_internal=(id=$2),is_duplicate=(id=$3) WHERE company_id=$1 AND id IN ($2,$3)", cid, internal, duplicate); err != nil {
		t.Fatal(err)
	}
	got := auditCall(t, h, token, "GET", "/v1/companies/"+cid+"/plan-fact/missed?from=2026-10-24&to=2026-10-24", nil, 200)
	rows := got["unexpected"].([]any)
	if len(rows) != 1 || rows[0].(map[string]any)["id"] != external {
		t.Fatalf("internal or duplicate cash was reported as unexpected business payment: %v", rows)
	}
}

func TestRecurringEventEditSurvivesPatternChange(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	p := auditCall(t, h, token, "POST", base+"/recurring", product.Doc{"title": "Rent", "direction": "out", "amount": 10000, "period": "monthly", "day_of_month": 24}, 201)
	r := h.call("GET", base+"/events?from=2026-10-24&to=2026-10-24", "", token)
	status(t, r, 200)
	event := decode[[]product.Doc](t, r)[0]
	auditCall(t, h, token, "PATCH", "/v1/events/"+event["id"].(string), product.Doc{"date": "2026-10-26", "amount": 12500}, 200)
	auditCall(t, h, token, "PATCH", "/v1/recurring/"+p["id"].(string), product.Doc{"title": "Renamed rent"}, 200)
	r = h.call("GET", base+"/events?from=2026-10-24&to=2026-10-26", "", token)
	status(t, r, 200)
	rows := decode[[]product.Doc](t, r)
	if len(rows) != 1 || rows[0]["id"] != event["id"] || rows[0]["date"] != "2026-10-26" || rows[0]["amount"] != float64(12500) {
		t.Fatal("pattern edit overwrote the user's individual installment", rows)
	}
	auditCall(t, h, token, "PATCH", "/v1/recurring/"+p["id"].(string), product.Doc{"confirmed": false}, 200)
	r = h.call("GET", base+"/events", "", token)
	status(t, r, 200)
	if rows = decode[[]product.Doc](t, r); len(rows) != 1 || rows[0]["id"] != event["id"] {
		t.Fatal("revoking a schedule removed an explicit user override", rows)
	}
}

func TestRevokingRecurringConfirmationRemovesFalseOverduePlans(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	p := auditCall(t, h, token, "POST", base+"/recurring", product.Doc{"title": "Rent", "direction": "out", "amount": 10000, "period": "monthly", "day_of_month": 24}, 201)
	r := h.call("GET", base+"/events", "", token)
	status(t, r, 200)
	if _, err := h.db.Pool.Exec(context.Background(), "UPDATE planned_events SET event_date='2026-10-22',status='missed' WHERE company_id=$1 AND extra->>'recurring_id'=$2", cid, p["id"]); err != nil {
		t.Fatal(err)
	}
	auditCall(t, h, token, "PATCH", "/v1/recurring/"+p["id"].(string), product.Doc{"confirmed": false}, 200)
	missed := auditCall(t, h, token, "GET", base+"/plan-fact/missed?from=2026-10-22&to=2026-10-23", nil, 200)
	if len(missed["missed"].([]any)) != 0 {
		t.Fatal("revoked schedule still reports unpaid automatic obligations", missed)
	}
}

func TestUnconfirmedRecurringMigrationPreservesPaidAndUserPlans(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	p := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/recurring", product.Doc{"title": "Candidate", "direction": "out", "amount": 10000, "period": "monthly", "confirmed": false}, 201)
	ctx := context.Background()
	for _, state := range []string{"expected", "missed", "received", "override"} {
		status := state
		if state == "override" {
			status = "expected"
		}
		_, err := h.db.Pool.Exec(ctx, `INSERT INTO planned_events(id,company_id,source_kind,event_date,amount,direction,title,category,probability,status,extra) VALUES($1,$2,'recurring','2026-10-22',10000,'out',$3,'rent',1,$4,$5)`, uuid.NewString(), cid, state, status, mustAuditJSON(product.Doc{"recurring_id": p["id"], "user_override": state == "override"}))
		if err != nil {
			t.Fatal(err)
		}
	}
	raw, err := migrations.Files.ReadFile("00008_recurring_confirmation.sql")
	if err != nil {
		t.Fatal(err)
	}
	up := strings.SplitN(string(raw), "-- +goose Down", 2)[0]
	if _, err = h.db.Pool.Exec(ctx, up); err != nil {
		t.Fatal(err)
	}
	var remaining int
	if err = h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM planned_events WHERE company_id=$1 AND (title IN ('received','override'))", cid).Scan(&remaining); err != nil {
		t.Fatal(err)
	}
	if remaining != 2 {
		t.Fatal("migration removed paid history or user overrides", remaining)
	}
	if err = h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM planned_events WHERE company_id=$1", cid).Scan(&remaining); err != nil {
		t.Fatal(err)
	}
	if remaining != 2 {
		t.Fatal("migration retained unconfirmed automatic obligations", remaining)
	}
}
