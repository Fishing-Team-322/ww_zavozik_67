package httpapi_test

import (
	"context"
	"encoding/json"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/migrations"
	"github.com/google/uuid"
	"strings"
	"testing"
	"time"
)

type auditFlatML struct{}

func (auditFlatML) Models(context.Context) ([]forecast.ModelInfo, error) { return nil, nil }
func (auditFlatML) Forecast(_ context.Context, r forecast.StochasticRequest) (forecast.StochasticForecast, error) {
	sf := forecast.StochasticForecast{ModelUsed: "seasonal_naive", FlowScope: r.FlowScope}
	for d := 0; d < r.Horizon; d++ {
		sf.Dates = append(sf.Dates, r.History[len(r.History)-1].Date.AddDate(0, 0, d+1))
	}
	for p := 0; p < r.NPaths; p++ {
		sf.Inflow = append(sf.Inflow, make([]float64, r.Horizon))
		sf.Outflow = append(sf.Outflow, make([]float64, r.Horizon))
	}
	return sf, nil
}
func auditSetup(t *testing.T) (*harness, *product.Service, string, string) {
	h := integration(t)
	token, _ := h.register("audit@example.test")
	s := &product.Service{DB: h.db, ML: auditFlatML{}, Fallback: forecast.SeasonalNaive{}}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: s, Log: testLogger()}).Handler()
	r := h.call("POST", "/v1/companies", `{"name":"Synthetic audit","legal_form":"ООО","industry":"services"}`, token)
	status(t, r, 201)
	cid := decode[product.Doc](t, r)["id"].(string)
	seedCaseHistory(t, h, cid, time.Date(2026, 10, 23, 0, 0, 0, 0, time.UTC), 90)
	return h, s, token, cid
}
func auditCall(t *testing.T, h *harness, token, method, path string, b any, want int) product.Doc {
	t.Helper()
	raw := ""
	if b != nil {
		v, _ := json.Marshal(b)
		raw = string(v)
	}
	r := h.call(method, path, raw, token)
	status(t, r, want)
	if want == 204 {
		return nil
	}
	return decode[product.Doc](t, r)
}
func auditOperation(t *testing.T, h *harness, cid, dt, party, inn string, amount, balance float64) string {
	t.Helper()
	id := uuid.NewString()
	_, e := h.db.Pool.Exec(context.Background(), `INSERT INTO operations(id,company_id,op_date,amount,direction,counterparty_name,counterparty_inn,purpose,balance_eod,category,category_method,dedup_hash,extra) VALUES($1,$2,$3,$4,'in',$5,$6,'Synthetic audit',$7,'revenue_b2b','rule',$1,'{}')`, id, cid, dt, amount, party, inn, balance)
	if e != nil {
		t.Fatal(e)
	}
	return id
}
func auditForecast(t *testing.T, h *harness, token, cid string) product.Doc {
	return auditCall(t, h, token, "GET", "/v1/companies/"+cid+"/forecast", nil, 200)
}

func TestAuditRecurringPatchPersistsFinancialFields(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	p := auditCall(t, h, token, "POST", base+"/recurring", product.Doc{"title": "Rent", "direction": "out", "amount": 10000, "period": "monthly", "category": "rent", "counterparty_name": "Old supplier"}, 201)
	got := auditCall(t, h, token, "PATCH", "/v1/recurring/"+p["id"].(string), product.Doc{"direction": "in", "category": "revenue_b2b", "counterparty_name": "New customer"}, 200)
	if got["direction"] != "in" || got["category"] != "revenue_b2b" {
		t.Errorf("BUG: PATCH returned old financial fields: %s", mustAuditJSON(got))
	}
}
func mustAuditJSON(v any) string { b, _ := json.Marshal(v); return string(b) }

func TestAuditInvoiceEditPreservesConsumedBankFact(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	mk := func(num string) product.Doc {
		return auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": num, "direction": "issued", "amount": 10000, "issued_at": "2026-10-20", "due_at": "2026-10-24", "counterparty_name": "Client 421", "additional": true}, 201)
	}
	first := mk("A-001")
	opID := auditOperation(t, h, cid, "2026-10-24", "Client 421", "7707083893", 10000, 119000)
	drainCase(t, s)
	first = auditCall(t, h, token, "PATCH", "/v1/invoices/"+first["id"].(string), product.Doc{"number": "A-001 corrected"}, 200)
	if first["paid_amount"] != float64(10000) {
		t.Fatal("first invoice was not settled", first)
	}
	second := mk("A-002")
	drainCase(t, s)
	var raw []byte
	e := h.db.Pool.QueryRow(context.Background(), "SELECT data FROM product_documents WHERE id=$1", second["id"]).Scan(&raw)
	if e != nil {
		t.Fatal(e)
	}
	var secondState product.Doc
	_ = json.Unmarshal(raw, &secondState)
	if secondState["paid_amount"] == float64(10000) {
		t.Errorf("BUG: one bank operation %s paid both invoices after editing the first: first=%v second=%v", opID, first["paid_amount"], secondState["paid_amount"])
	}
	// Deleting the documents must not make their consumed bank fact available.
	auditCall(t, h, token, "DELETE", "/v1/invoices/"+first["id"].(string), nil, 204)
	auditCall(t, h, token, "DELETE", "/v1/invoices/"+second["id"].(string), nil, 204)
	third := mk("A-003")
	drainCase(t, s)
	if e = h.db.Pool.QueryRow(context.Background(), "SELECT data FROM product_documents WHERE id=$1", third["id"]).Scan(&raw); e != nil {
		t.Fatal(e)
	}
	if err := json.Unmarshal(raw, &secondState); err != nil {
		t.Fatal(err)
	}
	if secondState["paid_amount"] != float64(0) {
		t.Fatal("deleted invoice released a bank fact", secondState)
	}
	var reserved int
	if e = h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM operation_settlements WHERE company_id=$1 AND operation_id=$2", cid, opID).Scan(&reserved); e != nil {
		t.Fatal(e)
	}
	if reserved != 1 {
		t.Fatalf("expected exactly one persistent settlement, got %d", reserved)
	}
}
func TestAuditReconcileMustRespectCounterpartyINN(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	event := auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-10-24", "title": "Payment from INN A", "amount": 4000, "direction": "in", "counterparty_name": "ООО Ромашка", "counterparty_inn": "7707083893"}, 201)
	auditOperation(t, h, cid, "2026-10-24", "ООО Ромашка", "7736050003", 4000, 113000)
	drainCase(t, s)
	var got string
	e := h.db.Pool.QueryRow(context.Background(), "SELECT status FROM planned_events WHERE id=$1", event["id"]).Scan(&got)
	if e != nil {
		t.Fatal(e)
	}
	if got == "received" {
		t.Errorf("BUG: event for INN 7707083893 was settled by operation with INN 7736050003 (same name and amount)")
	}
}
func TestAuditMoveReceivedEventDoesNotCreateNewIncome(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	event := auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-10-20", "title": "Already received", "amount": 10000, "direction": "in", "status": "received"}, 201)
	auditCall(t, h, token, "POST", base+"/scenarios/preview", product.Doc{"steps": []product.Doc{{"kind": "move_event", "event_id": event["id"], "date": "2026-10-25"}}}, 400)
}
func TestAuditOverdueTaxRemainsAnOutstandingLiability(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	_, shiftErr := h.db.Pool.Exec(context.Background(), "UPDATE operations SET op_date=op_date-2 WHERE company_id=$1", cid)
	if shiftErr != nil {
		t.Fatal(shiftErr)
	}
	tax := auditCall(t, h, token, "POST", base+"/taxes", product.Doc{"request_id": uuid.NewString(), "kind": "other", "period": "audit", "year": 2026, "due_date": "2026-10-22", "amount": 200000, "title": "Unpaid tax", "source_ref": "Synthetic audit", "confirmed": true, "additional": true}, 201)
	before := auditForecast(t, h, token, cid)
	if len(before["gaps"].([]any)) == 0 {
		t.Fatal("fixture: expected tax gap before due date")
	}
	// Cover the due date and the next date without paying the liability.
	auditOperation(t, h, cid, "2026-10-22", "Unrelated client", "", 100, 109100)
	auditOperation(t, h, cid, "2026-10-23", "Unrelated client", "", 100, 109200)
	drainCase(t, s)
	after := auditForecast(t, h, token, cid)
	var state string
	e := h.db.Pool.QueryRow(context.Background(), "SELECT status FROM planned_events WHERE extra->>'tax_id'=$1", tax["id"]).Scan(&state)
	if e != nil {
		t.Fatal(e)
	}
	if state != "missed" {
		t.Fatalf("expected missed obligation, got %s", state)
	}
	if len(after["gaps"].([]any)) == 0 {
		t.Errorf("BUG: unpaid tax 200000 is missed, but forecast ignores it and reports no gap; opening=%v p50=%v", after["opening_balance"], after["points"].([]any)[0])
	}
	point := after["points"].([]any)[0].(map[string]any)
	if point["p50"] != float64(-90800) {
		t.Fatalf("debt must be counted exactly once: %v", point)
	}
	var original string
	if e = h.db.Pool.QueryRow(context.Background(), "SELECT event_date::text FROM planned_events WHERE extra->>'tax_id'=$1", tax["id"]).Scan(&original); e != nil {
		t.Fatal(e)
	}
	if original != "2026-10-22" {
		t.Fatalf("original due date was rewritten: %s", original)
	}
}
func TestAuditResolvedGapAlertDoesNotRemainActiveWithBrokenLink(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	tax := auditCall(t, h, token, "POST", base+"/taxes", product.Doc{"request_id": uuid.NewString(), "kind": "other", "period": "audit", "year": 2026, "due_date": "2026-10-24", "amount": 200000, "title": "Temporary tax", "source_ref": "Synthetic audit", "confirmed": true, "additional": true}, 201)
	drainCase(t, s)
	before := auditForecast(t, h, token, cid)
	gid := before["gaps"].([]any)[0].(map[string]any)["id"].(string)
	auditCall(t, h, token, "POST", "/v1/taxes/"+tax["id"].(string)+"/cancel", nil, 204)
	drainCase(t, s)
	after := auditForecast(t, h, token, cid)
	if len(after["gaps"].([]any)) != 0 {
		t.Fatal("fixture gap not resolved")
	}
	list := auditCall(t, h, token, "GET", base+"/alerts?kind=gap_risk", nil, 200)
	active := 0
	for _, v := range list["items"].([]any) {
		if !v.(map[string]any)["read"].(bool) {
			active++
		}
	}
	linked := h.call("GET", base+"/gaps/"+gid, "", token)
	if active != 0 {
		t.Errorf("resolved gap still has %d unread warning(s)", active)
	}
	if linked.Code != 404 {
		t.Fatalf("obsolete gap should no longer be in the current forecast: %d", linked.Code)
	}
	for _, v := range list["items"].([]any) {
		ref := v.(map[string]any)["ref"].(map[string]any)
		if ref["screen"] != "forecast" {
			t.Errorf("resolved warning still links to an obsolete gap: %v", ref)
		}
	}
	// The same dated gap can recur. Reopen its warning instead of silently
	// keeping the old resolved/read state.
	auditCall(t, h, token, "POST", base+"/taxes", product.Doc{"request_id": uuid.NewString(), "kind": "other", "period": "audit", "year": 2026, "due_date": "2026-10-24", "amount": 200000, "title": "Recurred tax", "source_ref": "Synthetic audit", "confirmed": true, "additional": true}, 201)
	drainCase(t, s)
	reopened := auditCall(t, h, token, "GET", base+"/alerts?kind=gap_risk", nil, 200)
	if len(reopened["items"].([]any)) != 1 {
		t.Fatal("recurrence created duplicate warnings", reopened)
	}
	alert := reopened["items"].([]any)[0].(map[string]any)
	if alert["read"] != false || alert["ref"].(map[string]any)["screen"] != "gap" {
		t.Fatal("risk was not reopened", alert)
	}
}
func TestAuditTenantBoundaryControl(t *testing.T) {
	h, _, owner, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	other, _ := h.register("audit-outsider@example.test")
	event := auditCall(t, h, owner, "POST", base+"/events", product.Doc{"date": "2026-10-24", "title": "Private synthetic plan", "amount": 100, "direction": "out"}, 201)
	for _, path := range []string{base + "/events", base + "/forecast", base + "/updates", base + "/taxes"} {
		status(t, h.call("GET", path, "", other), 404)
	}
	status(t, h.call("PATCH", "/v1/events/"+event["id"].(string), `{"amount":999}`, other), 404)
	status(t, h.call("DELETE", "/v1/events/"+event["id"].(string), "", other), 404)
}

func TestSettlementMigrationPreservesLegacyBankMatches(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	event := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/events", product.Doc{"date": "2026-10-24", "title": "Legacy paid event", "amount": 10000, "direction": "in"}, 201)
	op := auditOperation(t, h, cid, "2026-10-24", "Legacy client", "", 10000, 119000)
	ctx := context.Background()
	if _, e := h.db.Pool.Exec(ctx, "UPDATE planned_events SET status='received',matched_operation_id=$2 WHERE id=$1", event["id"], op); e != nil {
		t.Fatal(e)
	}
	// Recreate only the new table from the actual migration; old facts survive.
	if _, e := h.db.Pool.Exec(ctx, "DROP TABLE operation_settlements"); e != nil {
		t.Fatal(e)
	}
	raw, e := migrations.Files.ReadFile("00007_operation_settlements.sql")
	if e != nil {
		t.Fatal(e)
	}
	up := strings.SplitN(string(raw), "-- +goose Down", 2)[0]
	if _, e = h.db.Pool.Exec(ctx, up); e != nil {
		t.Fatal(e)
	}
	var count int
	if e = h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM operation_settlements WHERE company_id=$1 AND operation_id=$2", cid, op).Scan(&count); e != nil {
		t.Fatal(e)
	}
	if count != 1 {
		t.Fatalf("legacy match lost during migration: %d", count)
	}
}
