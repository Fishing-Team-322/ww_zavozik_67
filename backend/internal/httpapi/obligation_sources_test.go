package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestExternalBankAndTaxObligationsReachForecast(t *testing.T) {
	for _, kind := range []string{"bank_api", "tax_api"} {
		t.Run(kind, func(t *testing.T) {
			h, s, token, cid := auditSetup(t)
			base := "/v1/companies/" + cid
			auditCall(t, h, token, "PATCH", base, product.Doc{"inn": "7707083893"}, 200)
			item := product.Doc{"external_id": "obligation-1", "kind": "salary", "title": "Salary project", "due_date": "2026-10-28", "amount_kopecks": int64(10001), "direction": "out", "status": "expected", "counterparty_name": "Payroll"}
			if kind == "tax_api" {
				item = product.Doc{"external_id": "vat-2026-q3", "kind": "tax", "title": "VAT liability from accounting", "amount_kopecks": int64(10001), "direction": "out", "status": "expected", "tax_kind": "vat", "period": "q3", "year": 2026}
			}
			mu := sync.Mutex{}
			feed := product.Doc{"company_inn": "7707083893", "as_of": "2026-10-23", "complete": true, "items": []any{item}}
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "Bearer private-feed-token" {
					w.WriteHeader(401)
					return
				}
				mu.Lock()
				defer mu.Unlock()
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(feed)
			}))
			defer upstream.Close()
			u, _ := url.Parse(upstream.URL)
			s.AllowedSourceHosts = []string{u.Host}
			s.EncryptionKey = bytes.Repeat([]byte("s"), 32)
			source := auditCall(t, h, token, "POST", base+"/sources", product.Doc{"kind": kind, "title": "Connected read-only system", "config": product.Doc{"url": upstream.URL, "token": "private-feed-token"}}, 201)
			id := source["id"].(string)
			if strings.Contains(mustAuditJSON(source), "private-feed-token") {
				t.Fatal("credentials leaked", source)
			}
			auditCall(t, h, token, "POST", "/v1/sources/"+id+"/test", nil, 200)
			syncSource := func(want string) {
				t.Helper()
				job := auditCall(t, h, token, "POST", "/v1/sources/"+id+"/sync", nil, 202)
				drainCase(t, s)
				result := auditCall(t, h, token, "GET", "/v1/jobs/"+job["id"].(string), nil, 200)
				if result["status"] != want {
					t.Fatal(result)
				}
			}
			syncSource("done")
			status(t, h.call("GET", base+"/sources", "", token), 200)
			var count int
			if e := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM planned_events WHERE company_id=$1 AND source_id=$2", cid, id).Scan(&count); e != nil {
				t.Fatal(e)
			}
			want := 1
			if kind == "tax_api" {
				want = 3
			}
			if count != want {
				t.Fatal("wrong installment count", count, want)
			}
			out := auditForecast(t, h, token, cid)
			last := out["points"].([]any)[29].(map[string]any)
			wantDelta := 100.01
			if kind == "tax_api" {
				wantDelta = 33.34
			}
			if math.Abs(out["opening_balance"].(float64)-last["p50"].(float64)-wantDelta) > .011 {
				t.Fatal("external obligation missing or duplicated", out)
			}
			var revision int64
			h.db.Pool.QueryRow(context.Background(), "SELECT data_revision FROM companies WHERE id=$1", cid).Scan(&revision)
			syncSource("done")
			var after int64
			h.db.Pool.QueryRow(context.Background(), "SELECT data_revision FROM companies WHERE id=$1", cid).Scan(&after)
			if after != revision {
				t.Fatal("identical sync changed financial revision", revision, after)
			}
			if kind == "tax_api" {
				taxes := auditCall(t, h, token, "GET", base+"/taxes?year=2026", nil, 200)
				if len(taxes["obligations"].([]any)) != 1 {
					t.Fatal(taxes)
				}
				liability := taxes["obligations"].([]any)[0].(map[string]any)
				if liability["editable"] != false || liability["source"] != "tax_api" {
					t.Fatal("UI must retain external ownership", liability)
				}
			}
			// Foreign-company and incomplete feeds must not replace committed plans.
			mu.Lock()
			feed["company_inn"] = "7800000000"
			mu.Unlock()
			syncSource("failed")
			mu.Lock()
			feed["company_inn"] = "7707083893"
			feed["complete"] = false
			feed["items"] = []any{}
			mu.Unlock()
			syncSource("failed")
			var active int
			h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM planned_events WHERE company_id=$1 AND source_id=$2 AND status='expected'", cid, id).Scan(&active)
			if active != want {
				t.Fatal("bad feed destroyed prior snapshot", active)
			}
			mu.Lock()
			feed["complete"] = true
			mu.Unlock()
			syncSource("done")
			final := auditForecast(t, h, token, cid)
			if final["points"].([]any)[29].(map[string]any)["p50"] != final["opening_balance"] {
				t.Fatal("cancelled source plans still affect forecast", final)
			}
		})
	}
}

func TestObligationSourceRequiresExplicitTrustedHost(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	s.EncryptionKey = bytes.Repeat([]byte("s"), 32)
	auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/sources", product.Doc{"kind": "bank_api", "title": "Unapproved host", "config": product.Doc{"url": "https://unapproved.example/plans", "token": "secret"}}, 403)
}
