package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/xuri/excelize/v2"
)

func TestProductSourceAdaptersAndRecovery(t *testing.T) {
	h := integration(t)
	ctx := context.Background()
	owner, _ := h.register("adapters@example.com")
	_, e := h.db.Pool.Exec(ctx, "UPDATE users SET role='admin' WHERE email='adapters@example.com'")
	if e != nil {
		t.Fatal(e)
	}
	service := &product.Service{DB: h.db, Fallback: forecast.SeasonalNaive{}, EncryptionKey: bytes.Repeat([]byte("k"), 32)}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: service, Log: testLogger()}).Handler()
	call := func(method, path string, body any, want int) product.Doc {
		t.Helper()
		raw := ""
		if body != nil {
			b, e := json.Marshal(body)
			if e != nil {
				t.Fatal(e)
			}
			raw = string(b)
		}
		r := h.call(method, path, raw, owner)
		status(t, r, want)
		if r.Body.Len() == 0 {
			return nil
		}
		return decode[product.Doc](t, r)
	}
	c := call("POST", "/v1/companies", product.Doc{"name": "Adapters", "legal_form": "ООО", "industry": "services", "inn": "7700000000"}, 201)
	cid := c["id"].(string)
	base := "/v1/companies/" + cid
	emptyCompany := call("GET", "/v1/admin/companies/"+cid, nil, 200)
	if emptyCompany["forecast"] != nil {
		t.Fatal("empty company has a forecast")
	}
	registryCompany := call("POST", "/v1/companies", product.Doc{"name": "Registry fixture", "legal_form": "ООО", "industry": "tests", "inn": "7707083893"}, 201)
	registrySource := call("POST", "/v1/companies/"+registryCompany["id"].(string)+"/sources", product.Doc{"kind": "fns", "title": "Registry fixture", "config": product.Doc{}}, 201)
	registryPath := "/v1/sources/" + registrySource["id"].(string)
	call("POST", registryPath+"/test", nil, 503)
	if state := call("GET", registryPath, nil, 200); state["status"] != "error" {
		t.Fatal("failed registry test must persist error status", state)
	}
	service.DaDataToken = "fixture-token"
	service.HTTP = &http.Client{Transport: sourceFixtureTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "suggestions.dadata.ru" {
			t.Fatal("unexpected provider destination")
		}
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"suggestions":[{"data":{"inn":"7707083893","ogrn":"1027700132195","type":"LEGAL","name":{"short_with_opf":"Registry fixture"},"state":{"status":"ACTIVE"}}}]}`))}, nil
	})}
	call("POST", registryPath+"/test", nil, 200)
	if state := call("GET", registryPath, nil, 200); state["status"] != "ok" || state["error"] != nil {
		t.Fatal("successful registry retry must clear error status", state)
	}
	service.DaDataToken, service.HTTP = "", nil
	upload := func(name string, data []byte, want int) product.Doc {
		t.Helper()
		buf := &bytes.Buffer{}
		m := multipart.NewWriter(buf)
		part, e := m.CreateFormFile("file", name)
		if e != nil {
			t.Fatal(e)
		}
		part.Write(data)
		m.Close()
		r := httptest.NewRequest("POST", base+"/uploads", buf)
		r.Header.Set("Authorization", "Bearer "+owner)
		r.Header.Set("Content-Type", m.FormDataContentType())
		w := httptest.NewRecorder()
		h.handler.ServeHTTP(w, r)
		status(t, w, want)
		return decode[product.Doc](t, w)
	}
	drain := func() {
		t.Helper()
		for i := 0; i < 100; i++ {
			worked, e := service.ProcessOne(ctx)
			if e != nil {
				t.Fatal(e)
			}
			if !worked {
				return
			}
		}
		t.Fatal("queue did not settle")
	}
	done := func(job product.Doc) product.Doc {
		t.Helper()
		drain()
		d := call("GET", "/v1/jobs/"+job["id"].(string), nil, 200)
		if d["status"] != "done" {
			t.Fatalf("failed job: %+v", d)
		}
		return d
	}
	// Google Sheets uses the same queue and importer, with a deterministic API fixture.
	denySheet := false
	service.HTTP = &http.Client{Transport: sourceFixtureTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "sheets.googleapis.com" || r.URL.Path != "/v4/spreadsheets/e2e-sheet/values/A1:Z10001" || r.Header.Get("X-Goog-Api-Key") != "fixture-key" {
			t.Fatal("unexpected Google Sheets request")
		}
		code, body := 200, `{"values":[["date","amount","direction","counterparty"],["2026-10-19","85","in","Sheet fixture"]]}`
		if denySheet {
			code, body = 403, `{}`
		}
		return &http.Response{StatusCode: code, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}, nil
	})}
	sheet := call("POST", base+"/sources", product.Doc{"kind": "gsheets", "title": "Sheet fixture", "config": product.Doc{"spreadsheet_id": "e2e-sheet", "api_key": "fixture-key"}}, 201)
	sheetPath := "/v1/sources/" + sheet["id"].(string)
	call("POST", sheetPath+"/test", nil, 200)
	firstSheet := done(call("POST", sheetPath+"/sync", nil, 202))
	if result := firstSheet["result"].(map[string]any); result["added"] != float64(1) {
		t.Fatal("sheet import", result)
	}
	repeatSheet := done(call("POST", sheetPath+"/sync", nil, 202))
	if result := repeatSheet["result"].(map[string]any); result["added"] != float64(0) || result["duplicates"] != float64(1) {
		t.Fatal("sheet repeat", result)
	}
	denySheet = true
	call("POST", sheetPath+"/test", nil, 502)
	if state := call("GET", sheetPath, nil, 200); state["status"] != "error" {
		t.Fatal("sheet failure status", state)
	}
	service.HTTP = nil
	// Unknown headers require an owner-confirmed mapping, then use the same importer.
	u := upload("unknown.csv", []byte("When,Value,Side,Who\n2026-10-20,100,in,Client\n"), 200)
	uid := u["upload_id"].(string)
	preview := call("GET", "/v1/uploads/"+uid+"/preview", nil, 200)
	if len(preview["rows"].([]any)) != 1 {
		t.Fatal(preview)
	}
	done(call("POST", "/v1/uploads/"+uid+"/mapping", product.Doc{"mapping": product.Doc{"date": "When", "amount": "Value", "direction": "Side", "counterparty": "Who"}}, 202))
	book := excelize.NewFile()
	for i, row := range [][]any{{"date", "amount", "direction", "counterparty"}, {"2026-10-21", 120, "in", "XLSX Client"}} {
		cell, _ := excelize.CoordinatesToCellName(1, i+1)
		book.SetSheetRow("Sheet1", cell, &row)
	}
	b, e := book.WriteToBuffer()
	if e != nil {
		t.Fatal(e)
	}
	book.Close()
	done(upload("data.xlsx", b.Bytes(), 202))
	for _, name := range []string{"onec_bank_utf8.txt", "onec_bank_cp1251.txt"} {
		data, e := os.ReadFile("../../../integrations/testdata/" + name)
		if e != nil {
			t.Fatal(e)
		}
		if name == "onec_bank_utf8.txt" {
			data = append([]byte{0xef, 0xbb, 0xbf}, data...)
		}
		done(upload(name, data, 202))
	}
	// Credentials are encrypted in the normalized source table and never returned.
	mock := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u, p, ok := r.BasicAuth()
		if !ok || u != "reader" || p != "secret-value" {
			t.Error("missing adapter credentials")
		}
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(r.URL.Path, "/$metadata") {
			io.WriteString(w, `<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx"><edmx:DataServices><Schema xmlns="http://schemas.microsoft.com/ado/2009/11/edm" Namespace="StandardODATA"><EntityType Name="Document_BankReceipt"><Property Name="Ref_Key" Type="Edm.String"/><Property Name="Number" Type="Edm.String"/><Property Name="Date" Type="Edm.DateTime"/><Property Name="ExecutionDate" Type="Edm.DateTime"/><Property Name="Amount" Type="Edm.Double"/><Property Name="Posted" Type="Edm.Boolean"/><Property Name="Account_Key" Type="Edm.String"/><Property Name="Counterparty" Type="Edm.String"/><Property Name="PaymentPurpose" Type="Edm.String"/></EntityType><EntityType Name="Document_BankPayment"><Property Name="Ref_Key" Type="Edm.String"/><Property Name="Number" Type="Edm.String"/><Property Name="Date" Type="Edm.DateTime"/><Property Name="ExecutionDate" Type="Edm.DateTime"/><Property Name="Amount" Type="Edm.Double"/><Property Name="Posted" Type="Edm.Boolean"/><Property Name="Account_Key" Type="Edm.String"/><Property Name="Counterparty" Type="Edm.String"/><Property Name="PaymentPurpose" Type="Edm.String"/></EntityType><EntityContainer Name="Default"><EntitySet Name="Document_BankReceipt" EntityType="StandardODATA.Document_BankReceipt"/><EntitySet Name="Document_BankPayment" EntityType="StandardODATA.Document_BankPayment"/></EntityContainer></Schema></edmx:DataServices></edmx:Edmx>`)
		} else if strings.HasSuffix(r.URL.Path, "/standard.odata/") {
			io.WriteString(w, `{"value":[{"name":"Document_BankReceipt","url":"Document_BankReceipt"},{"name":"Document_BankPayment","url":"Document_BankPayment"}]}`)
		} else if strings.HasSuffix(r.URL.Path, "Document_BankReceipt") {
			io.WriteString(w, `{"value":[{"Ref_Key":"backend-in-1","Number":"1","Date":"2026-10-22","ExecutionDate":"2026-10-22","Amount":1250.75,"Posted":true,"Account_Key":"bank-account-1","Counterparty":{"INN":"7800000000","Description":"Backend client"},"PaymentPurpose":"Services"}]}`)
		} else {
			io.WriteString(w, `{"value":[]}`)
		}
	}))
	defer mock.Close()
	raw, e := os.ReadFile("../../../integrations/testdata/onec_odata_mock.json")
	if e != nil {
		t.Fatal(e)
	}
	var cfg product.Doc
	if e = json.Unmarshal(raw, &cfg); e != nil {
		t.Fatal(e)
	}
	cfg["base_url"] = mock.URL + "/odata/standard.odata/"
	cfg["username"] = "reader"
	cfg["password"] = "secret-value"
	service.AllowedSourceHosts = []string{strings.TrimPrefix(mock.URL, "http://")}
	draft := call("POST", base+"/sources", product.Doc{"title": "Draft OData", "kind": "onec_odata", "config": product.Doc{"base_url": mock.URL + "/odata/standard.odata/", "username": "reader", "password": "secret-value"}}, 201)
	if draft["status"] != "pending" {
		t.Fatal("new OData source must wait for connection test", draft)
	}
	draftCheck := call("POST", "/v1/sources/"+draft["id"].(string)+"/test", nil, 200)
	if draftCheck["ok"] != true || draftCheck["ready_to_sync"] != false || draftCheck["discovery"] == nil {
		t.Fatal("OData draft should discover metadata before mapping", draftCheck)
	}
	if after := call("GET", "/v1/sources/"+draft["id"].(string), nil, 200); after["status"] != "mapping_required" {
		t.Fatal("draft status should request mapping", after)
	}
	source := call("POST", base+"/sources", product.Doc{"title": "Test OData", "kind": "onec_odata", "config": cfg}, 201)
	sid := source["id"].(string)
	checked := call("POST", "/v1/sources/"+sid+"/test", nil, 200)
	if checked["ok"] != true || checked["ready_to_sync"] != true || checked["discovery"] == nil {
		t.Fatal("OData metadata discovery failed", checked)
	}
	done(call("POST", "/v1/sources/"+sid+"/sync", nil, 202))
	done(call("POST", "/v1/admin/integrations/"+sid+"/retry", nil, 202))
	var secret []byte
	var extra string
	if e = h.db.Pool.QueryRow(ctx, "SELECT config_secret,extra::text FROM sources WHERE id=$1", sid).Scan(&secret, &extra); e != nil {
		t.Fatal(e)
	}
	if bytes.Contains(secret, []byte("secret-value")) || strings.Contains(extra, "secret-value") || strings.Contains(fmt.Sprint(source), "secret-value") {
		t.Fatal("source secret leak")
	}
	service.EncryptionKey = bytes.Repeat([]byte("z"), 32)
	call("POST", "/v1/sources/"+sid+"/test", nil, 503)
	service.EncryptionKey = bytes.Repeat([]byte("k"), 32)
	service.AllowedSourceHosts = nil
	call("POST", "/v1/sources/"+sid+"/test", nil, 403)
	// An external trainer must explicitly confirm a real artifact version.
	trainer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.Header.Get("Authorization") != "Bearer training-secret" {
			t.Error("trainer auth")
		}
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"trained":true,"model_version":"test-artifact-v1"}`)
	}))
	defer trainer.Close()
	service.TrainingURL = trainer.URL
	service.TrainingToken = "training-secret"
	trained := done(call("POST", "/v1/admin/models/auto/retrain", nil, 202))
	if trained["result"].(map[string]any)["model_version"] != "test-artifact-v1" {
		t.Fatal(trained)
	}
	// A crashed worker's lease is reclaimable by another worker; no request memory needed.
	job := call("POST", base+"/export", nil, 202)
	if _, e = h.db.Pool.Exec(ctx, "UPDATE product_jobs SET status='running',locked_at=now()-interval '10 minutes',attempts=1 WHERE id=$1", job["id"]); e != nil {
		t.Fatal(e)
	}
	done(job)
	invoice := call("POST", base+"/invoices", product.Doc{"number": "MATCH-1", "direction": "issued", "amount": 100, "issued_at": "2026-10-20", "due_at": "2026-10-20", "counterparty_name": "Client"}, 201)
	for i := 0; i < 2; i++ {
		call("POST", base+"/events", product.Doc{"title": fmt.Sprintf("Ambiguous %d", i), "date": "2026-10-21", "amount": 120, "direction": "in", "counterparty_name": "XLSX Client"}, 201)
	}
	drain()
	var paid float64
	if e = h.db.Pool.QueryRow(ctx, "SELECT (data->>'paid_amount')::float8 FROM product_documents WHERE id=$1", invoice["id"]).Scan(&paid); e != nil || paid != 100 {
		t.Fatalf("invoice reconciliation: %v %v", paid, e)
	}
	var matched int
	if e = h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM planned_events WHERE company_id=$1 AND title LIKE 'Ambiguous%' AND matched_operation_id IS NOT NULL", cid).Scan(&matched); e != nil || matched != 0 {
		t.Fatalf("ambiguous payment matched: %d %v", matched, e)
	}
	// Signals are based on observed facts and can be triaged through the admin API.
	done(upload("signals.csv", []byte("date,amount,direction,purpose\n2026-10-22,10,out,A\n2026-10-22,20,out,B\n2026-10-22,30,out,C\n2026-10-22,40,out,D\n2026-10-22,50,out,E\n2026-10-22,1000000,out,Large purchase\n"), 202))
	signals := call("GET", "/v1/admin/antifraud/signals", nil, 200)["items"].([]any)
	if len(signals) == 0 {
		t.Fatal("missing observed signal")
	}
	signalID := signals[0].(map[string]any)["id"].(string)
	call("GET", "/v1/admin/antifraud/signals/"+signalID, nil, 200)
	closed := call("PATCH", "/v1/admin/antifraud/signals/"+signalID, product.Doc{"status": "closed", "resolution": "false_positive", "comment": "Confirmed planned purchase"}, 200)
	if closed["status"] != "closed" {
		t.Fatal(closed)
	}
	var userID string
	if e = h.db.Pool.QueryRow(ctx, "SELECT id::text FROM users WHERE email='adapters@example.com'").Scan(&userID); e != nil {
		t.Fatal(e)
	}
	if _, e = h.db.ProductSave(ctx, userID, cid, "alert", cid, product.Doc{"id": cid, "severity": "info", "kind": "data_stale", "title": "Test notice", "body": "Test notice", "read": false, "ref": product.Doc{"screen": "dashboard", "id": nil}}, true); e != nil {
		t.Fatal(e)
	}
	call("PATCH", "/v1/alerts/"+cid, product.Doc{"read": true}, 200)
}

type sourceFixtureTransport func(*http.Request) (*http.Response, error)

func (f sourceFixtureTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
