package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

// PostgreSQL + authenticated backend + an OData fixture. It proves the backend
// path, while the upstream is deliberately marked TESTED_WITH_MOCK.
func TestOneCObligationsBackendE2E(t *testing.T) {
	due, cancelled, failPlans := "2026-11-05", false, false
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if user, password, ok := r.BasicAuth(); !ok || user != "reader" || password != "secret-value" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "/standard.odata/"):
			fmt.Fprint(w, `{"value":[{"name":"Document_BankReceipt","url":"Document_BankReceipt"},{"name":"Document_BankPayment","url":"Document_BankPayment"},{"name":"Document_CustomerInvoice","url":"Document_CustomerInvoice"},{"name":"Document_Receipt_Detail","url":"Document_Receipt_Detail"}]}`)
		case strings.HasSuffix(r.URL.Path, "/$metadata"):
			fmt.Fprint(w, `<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx"><edmx:DataServices><Schema xmlns="http://schemas.microsoft.com/ado/2009/11/edm" Namespace="StandardODATA"><EntityType Name="Document_BankReceipt"><Property Name="Ref_Key"/><Property Name="Number"/><Property Name="Date"/><Property Name="ExecutionDate"/><Property Name="Amount"/><Property Name="Posted"/><Property Name="Account_Key"/><Property Name="Counterparty"/><Property Name="PaymentPurpose"/></EntityType><EntityType Name="Document_BankPayment"><Property Name="Ref_Key"/><Property Name="Number"/><Property Name="Date"/><Property Name="ExecutionDate"/><Property Name="Amount"/><Property Name="Posted"/><Property Name="Account_Key"/><Property Name="Counterparty"/><Property Name="PaymentPurpose"/></EntityType><EntityType Name="Document_CustomerInvoice"><Property Name="Ref_Key"/><Property Name="Number"/><Property Name="Date"/><Property Name="DueDate"/><Property Name="Amount"/><Property Name="Posted"/><Property Name="DeletionMark"/><Property Name="Organization_Key"/><Property Name="Currency_Key"/></EntityType><EntityType Name="Document_Receipt_Detail"><Property Name="Ref_Key"/><Property Name="LineNumber"/><Property Name="Invoice_Key"/><Property Name="Amount"/><Property Name="Posted"/></EntityType><EntityContainer Name="Default"><EntitySet Name="Document_BankReceipt" EntityType="StandardODATA.Document_BankReceipt"/><EntitySet Name="Document_BankPayment" EntityType="StandardODATA.Document_BankPayment"/><EntitySet Name="Document_CustomerInvoice" EntityType="StandardODATA.Document_CustomerInvoice"/><EntitySet Name="Document_Receipt_Detail" EntityType="StandardODATA.Document_Receipt_Detail"/></EntityContainer></Schema></edmx:DataServices></edmx:Edmx>`)
		case strings.HasSuffix(r.URL.Path, "Document_BankReceipt"):
			fmt.Fprint(w, `{"value":[{"Ref_Key":"payment-1","Number":"1","Date":"2026-10-22","ExecutionDate":"2026-10-22","Amount":100000,"Posted":true,"Account_Key":"bank-account-1","Counterparty":{"INN":"7800000000","Description":"Client"},"PaymentPurpose":"Invoice 10"}]}`)
		case strings.HasSuffix(r.URL.Path, "Document_BankPayment"):
			fmt.Fprint(w, `{"value":[]}`)
		case strings.HasSuffix(r.URL.Path, "Document_CustomerInvoice"):
			if failPlans {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			fmt.Fprintf(w, `{"value":[{"Ref_Key":"invoice-1","Number":"10","Date":"2026-10-20","DueDate":%q,"Amount":350000,"Posted":true,"DeletionMark":%t,"Organization_Key":"org-1","Currency_Key":"rub-1"}]}`, due, cancelled)
		case strings.HasSuffix(r.URL.Path, "Document_Receipt_Detail"):
			fmt.Fprint(w, `{"value":[{"Ref_Key":"payment-1","LineNumber":"1","Invoice_Key":"invoice-1","Amount":100000,"Posted":true}]}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer upstream.Close()
	h := integration(t)
	owner, _ := h.register("onec-plan-owner@example.test")
	outsider, _ := h.register("onec-plan-outsider@example.test")
	svc := &product.Service{DB: h.db, Fallback: forecast.SeasonalNaive{}, EncryptionKey: bytes.Repeat([]byte("k"), 32), AllowedSourceHosts: []string{strings.TrimPrefix(upstream.URL, "http://")}}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: svc, Log: testLogger()}).Handler()
	call := func(method, path string, body any, token string, want int) product.Doc {
		t.Helper()
		data := ""
		if body != nil {
			b, err := json.Marshal(body)
			if err != nil {
				t.Fatal(err)
			}
			data = string(b)
		}
		response := h.call(method, path, data, token)
		status(t, response, want)
		return decode[product.Doc](t, response)
	}
	company := call("POST", "/v1/companies", product.Doc{"name": "OneC plans", "legal_form": "ООО", "industry": "services", "inn": "7700000000"}, owner, 201)
	cid := company["id"].(string)
	raw, err := os.ReadFile("../../../integrations/testdata/onec_odata_mock.json")
	if err != nil {
		t.Fatal(err)
	}
	var cfg product.Doc
	if err = json.Unmarshal(raw, &cfg); err != nil {
		t.Fatal(err)
	}
	cfg["base_url"], cfg["username"], cfg["password"] = upstream.URL+"/odata/standard.odata/", "reader", "secret-value"
	cfg["plan_config"] = product.Doc{
		"data_mode": "live", "organization_ids": []string{"org-1"}, "rub_currency_ids": []string{"rub-1"},
		"invoices": []any{product.Doc{"entity_set": "Document_CustomerInvoice", "direction": "in", "fields": product.Doc{"external_id": "Ref_Key", "number": "Number", "document_date": "Date", "due_date": "DueDate", "amount": "Amount", "posted": "Posted", "deleted": "DeletionMark", "organization_key": "Organization_Key", "currency_key": "Currency_Key"}}},
		"payments": []any{product.Doc{"entity_set": "Document_Receipt_Detail", "invoice_entity_set": "Document_CustomerInvoice", "fields": product.Doc{"external_id": "Ref_Key", "line_number": "LineNumber", "invoice_key": "Invoice_Key", "amount": "Amount", "posted": "Posted"}}},
	}
	source := call("POST", "/v1/companies/"+cid+"/sources", product.Doc{"title": "OneC mock source", "kind": "onec_odata", "config": cfg}, owner, 201)
	sid := source["id"].(string)
	if got := call("POST", "/v1/sources/"+sid+"/test", nil, owner, 200); got["ready_to_sync"] != true {
		t.Fatal(got)
	}
	sync := func(wantAdd, wantUpdate, wantDuplicate int) {
		t.Helper()
		job := call("POST", "/v1/sources/"+sid+"/sync", nil, owner, 202)
		for i := 0; i < 15; i++ {
			if _, e := svc.ProcessOne(context.Background()); e != nil {
				t.Fatal(e)
			}
			state := call("GET", "/v1/jobs/"+job["id"].(string), nil, owner, 200)
			if state["status"] == "done" {
				result := state["result"].(map[string]any)
				if result["plans_added"] != float64(wantAdd) || result["plans_updated"] != float64(wantUpdate) || result["plans_duplicates"] != float64(wantDuplicate) {
					t.Fatalf("sync counters: %v", result)
				}
				return
			}
			if state["status"] == "failed" {
				t.Fatalf("sync failed: %v", state)
			}
		}
		t.Fatal("sync did not finish")
	}
	sync(1, 0, 0)
	read := func() product.Doc {
		response := h.call("GET", "/v1/companies/"+cid+"/events", "", owner)
		status(t, response, 200)
		items := decode[[]product.Doc](t, response)
		if len(items) != 1 {
			t.Fatalf("want one obligation, got %d", len(items))
		}
		return items[0]
	}
	first := read()
	if first["paid_kopecks"] != float64(10_000_000) || first["remaining_kopecks"] != float64(25_000_000) || first["status"] != "expected" || first["forecast_eligible"] != true || first["version"] != float64(1) {
		t.Fatal(first)
	}
	response := h.call("GET", "/v1/companies/"+cid+"/operations", "", owner)
	status(t, response, 200)
	if got := decode[product.Doc](t, response)["items"].([]any); len(got) != 1 {
		t.Fatal("bank fact missing or duplicated")
	}
	failPlans = true
	failedJob := call("POST", "/v1/sources/"+sid+"/sync", nil, owner, 202)
	for i := 0; i < 15; i++ {
		if _, e := svc.ProcessOne(context.Background()); e != nil {
			t.Fatal(e)
		}
		state := call("GET", "/v1/jobs/"+failedJob["id"].(string), nil, owner, 200)
		if state["status"] == "failed" {
			break
		}
		if i == 14 {
			t.Fatal("upstream failure did not fail sync")
		}
	}
	if kept := read(); kept["id"] != first["id"] || kept["version"] != float64(1) {
		t.Fatal("failed sync changed snapshot", kept)
	}
	failPlans = false
	sync(0, 0, 1)
	if read()["id"] != first["id"] {
		t.Fatal("repeat changed event identity")
	}
	due = "2026-11-19"
	sync(0, 1, 0)
	if moved := read(); moved["id"] != first["id"] || moved["due_date"] != due || moved["version"] != float64(2) {
		t.Fatal(moved)
	}
	cancelled = true
	sync(0, 1, 0)
	if ended := read(); ended["id"] != first["id"] || ended["status"] != "cancelled" || ended["remaining_kopecks"] != float64(0) || ended["forecast_eligible"] != false {
		t.Fatal(ended)
	}
	var versions int
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM onec_plan_versions WHERE company_id=$1 AND source_id=$2", cid, sid).Scan(&versions); err != nil || versions != 3 {
		t.Fatalf("history: %d, %v", versions, err)
	}
	status(t, h.call("GET", "/v1/companies/"+cid+"/events", "", outsider), 404)
	otherCompany := call("POST", "/v1/companies", product.Doc{"name": "Another OneC tenant", "legal_form": "ООО", "industry": "services", "inn": "7700000000"}, outsider, 201)
	otherCID := otherCompany["id"].(string)
	otherSource := call("POST", "/v1/companies/"+otherCID+"/sources", product.Doc{"title": "Same external invoice", "kind": "onec_odata", "config": cfg}, outsider, 201)
	otherJob := call("POST", "/v1/sources/"+otherSource["id"].(string)+"/sync", nil, outsider, 202)
	for i := 0; i < 15; i++ {
		if _, e := svc.ProcessOne(context.Background()); e != nil {
			t.Fatal(e)
		}
		state := call("GET", "/v1/jobs/"+otherJob["id"].(string), nil, outsider, 200)
		if state["status"] == "done" {
			break
		}
		if state["status"] == "failed" || i == 14 {
			t.Fatalf("other company sync: %v", state)
		}
	}
	otherResponse := h.call("GET", "/v1/companies/"+otherCID+"/events", "", outsider)
	status(t, otherResponse, 200)
	otherEvents := decode[[]product.Doc](t, otherResponse)
	if len(otherEvents) != 1 || otherEvents[0]["id"] == first["id"] {
		t.Fatalf("tenant keys collided: %v", otherEvents)
	}
	status(t, h.call("GET", "/v1/companies/"+otherCID+"/events", "", owner), 404)
}
