package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/obligationapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/obligations"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/google/uuid"
)

func TestOwnBankAPIEndToEndPreservesBankPaidPlans(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	auditCall(t, h, token, "PATCH", base, product.Doc{"inn": "7707083893"}, 200)
	read, admin := "read-bank-token-with-32-characters-min", "admin-bank-token-with-32-characters-min"
	provider, e := obligationapi.New(read, admin, filepath.Join(t.TempDir(), "bank.json"))
	if e != nil {
		t.Fatal(e)
	}
	server := httptest.NewServer(provider.Handler())
	defer server.Close()
	feed := obligations.Feed{CompanyINN: "7707083893", AsOf: "2026-10-23", Complete: true, Items: []obligations.Item{
		{ExternalID: "loan/2026-10", Kind: "loan_payment", Title: "Loan schedule", DueDate: "2026-10-26", AmountKopecks: 100000, Direction: "out", Status: "expected", CounterpartyName: "Our demo bank"},
		{ExternalID: "payroll/2026-10", Kind: "salary", Title: "Payroll project", DueDate: "2026-10-28", AmountKopecks: 200000, Direction: "out", Status: "expected", CounterpartyName: "Employees"},
		{ExternalID: "order/42", Kind: "payment_order", Title: "Unexecuted payment order", DueDate: "2026-10-29", AmountKopecks: 300000, Direction: "out", Status: "expected", CounterpartyName: "Supplier"},
	}}
	endpoint := server.URL + "/v1/companies/7707083893/bank/obligations"
	put := func() {
		t.Helper()
		raw, _ := json.Marshal(feed)
		r, _ := http.NewRequest("PUT", endpoint, bytes.NewReader(raw))
		r.Header.Set("Authorization", "Bearer "+admin)
		res, e := server.Client().Do(r)
		if e != nil {
			t.Fatal(e)
		}
		defer res.Body.Close()
		if res.StatusCode != 200 {
			t.Fatal(res.Status)
		}
	}
	put()
	u, _ := url.Parse(server.URL)
	s.AllowedSourceHosts = []string{u.Host}
	s.EncryptionKey = bytes.Repeat([]byte("b"), 32)
	source := auditCall(t, h, token, "POST", base+"/sources", product.Doc{"kind": "bank_api", "title": "Our demonstration bank", "config": product.Doc{"url": endpoint, "token": read}}, 201)
	syncSource := func() {
		t.Helper()
		job := auditCall(t, h, token, "POST", "/v1/sources/"+source["id"].(string)+"/sync", nil, 202)
		drainCase(t, s)
		if got := auditCall(t, h, token, "GET", "/v1/jobs/"+job["id"].(string), nil, 200); got["status"] != "done" {
			t.Fatal(got)
		}
	}
	syncSource()
	before := auditForecast(t, h, token, cid)
	if before["points"].([]any)[29].(map[string]any)["p50"] != before["opening_balance"].(float64)-6000 {
		t.Fatal("loan, payroll and order did not reach forecast", before)
	}
	// Early bank repayment consumes the plan; subsequent source sync cannot reopen it.
	_, e = h.db.Pool.Exec(context.Background(), `INSERT INTO operations(id,company_id,op_date,amount,direction,counterparty_name,purpose,balance_eod,category,category_method,dedup_hash) VALUES($1,$2,'2026-10-24',1000,'out','Our demo bank','Loan payment',$3,'loan_payment','rule',$1)`, uuid.NewString(), cid, before["opening_balance"].(float64)-1000)
	if e != nil {
		t.Fatal(e)
	}
	drainCase(t, s) // no event job was enqueued by the direct fixture insertion
	// Queue a normal recomputation just as statement import does.
	_, e = s.DB.ProductJob(context.Background(), tokenUserID(t, h, token), cid, "recompute", product.Doc{})
	if e != nil {
		t.Fatal(e)
	}
	drainCase(t, s)
	syncSource()
	after := auditForecast(t, h, token, cid)
	if after["points"].([]any)[29].(map[string]any)["p50"] != before["opening_balance"].(float64)-6000 {
		t.Fatal("bank receipt was applied twice", after)
	}
	var state string
	if e = h.db.Pool.QueryRow(context.Background(), "SELECT status FROM planned_events WHERE company_id=$1 AND source_id=$2 AND extra->>'external_id'='loan/2026-10'", cid, source["id"]).Scan(&state); e != nil || state != "received" {
		t.Fatal(state, e)
	}
	status(t, h.call("GET", base+"/sources", "", token), 200)
}

func tokenUserID(t *testing.T, h *harness, token string) string {
	t.Helper()
	me := auditCall(t, h, token, "GET", "/v1/me", nil, 200)
	return me["id"].(string)
}
