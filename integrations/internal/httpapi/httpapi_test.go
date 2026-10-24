package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/dadata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func upload(t *testing.T, handler http.Handler, company string, data []byte) *httptest.ResponseRecorder {
	t.Helper()
	var body bytes.Buffer
	w := multipart.NewWriter(&body)
	for k, v := range map[string]string{"company_id": company, "company_inn": "7700000000", "company_account": "40702810000000000001"} {
		if err := w.WriteField(k, v); err != nil {
			t.Fatal(err)
		}
	}
	f, err := w.CreateFormFile("file", "statement.txt")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.Write(data); err != nil {
		t.Fatal(err)
	}
	if err = w.Close(); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest("POST", "/v1/import/onec-bank", &body)
	r.Header.Set("Content-Type", w.FormDataContentType())
	r.Header.Set("Authorization", "Bearer local-operator-token")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, r)
	return rec
}

func TestCSVPreviewCommit(t *testing.T) {
	h := (API{Store: store.NewMemory(), SyncToken: "local-operator-token"}).Handler()
	call := func(mode string) *httptest.ResponseRecorder {
		var body bytes.Buffer
		w := multipart.NewWriter(&body)
		_ = w.WriteField("company_id", "demo-company")
		_ = w.WriteField("mode", mode)
		_ = w.WriteField("mapping", `{"category":"invoice","encoding":"utf-8"}`)
		f, err := w.CreateFormFile("file", "invoices.csv")
		if err != nil {
			t.Fatal(err)
		}
		_, _ = f.Write([]byte("external_id;date;amount;direction;due_date\ni1;2026-10-24;100,05;in;2026-11-05\n"))
		_ = w.Close()
		r := httptest.NewRequest("POST", "/v1/import/csv", &body)
		r.Header.Set("Content-Type", w.FormDataContentType())
		r.Header.Set("Authorization", "Bearer local-operator-token")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, r)
		return rec
	}
	if rec := call("preview"); rec.Code != 200 {
		t.Fatalf("preview: %d %s", rec.Code, rec.Body.String())
	}
	if rec := call("commit"); rec.Code != 200 {
		t.Fatalf("commit: %d %s", rec.Code, rec.Body.String())
	}
	if rec := call("commit"); rec.Code != 200 || !strings.Contains(rec.Body.String(), `"duplicates":1`) {
		t.Fatalf("duplicate: %d %s", rec.Code, rec.Body.String())
	}
}

func TestHTTPImportAndIsolation(t *testing.T) {
	data, err := os.ReadFile("../../testdata/onec_bank_utf8.txt")
	if err != nil {
		t.Fatal(err)
	}
	h := (API{Store: store.NewMemory(), SyncToken: "local-operator-token"}).Handler()
	for _, tc := range []struct {
		company              string
		accepted, duplicates int
	}{{"one", 2, 1}, {"one", 0, 3}, {"two", 2, 1}} {
		rec := upload(t, h, tc.company, data)
		if rec.Code != 200 {
			t.Fatalf("%d: %s", rec.Code, rec.Body.String())
		}
		var batch contracts.ImportBatch
		if err := json.Unmarshal(rec.Body.Bytes(), &batch); err != nil {
			t.Fatal(err)
		}
		if batch.SchemaVersion != "1.0" || batch.ImportID == "" || batch.ImportedAt == "" || batch.SourceMode != "file" || batch.PlannedEvents == nil || batch.Operations == nil || batch.Issues == nil {
			t.Fatal("missing contract fields")
		}
		if batch.Stats.Accepted != tc.accepted || batch.Stats.Duplicates != tc.duplicates {
			t.Fatalf("stats: %+v", batch.Stats)
		}
		if len(batch.Operations) != tc.accepted {
			t.Fatal("operations count")
		}
	}
	rec := httptest.NewRecorder()
	request := httptest.NewRequest("GET", "/v1/batches/one", nil)
	request.Header.Set("Authorization", "Bearer local-operator-token")
	h.ServeHTTP(rec, request)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"company_id":"one"`) || strings.Contains(rec.Body.String(), `"company_id":"two"`) {
		t.Fatal(rec.Body.String())
	}
}

func TestHealthAndProviderStatuses(t *testing.T) {
	h := (API{Store: store.NewMemory()}).Handler()
	health := httptest.NewRecorder()
	h.ServeHTTP(health, httptest.NewRequest("GET", "/healthz", nil))
	if health.Code != 200 || !strings.Contains(health.Body.String(), `"status":"ok"`) {
		t.Fatal(health.Body.String())
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "/v1/providers", nil))
	var got []providers.Status
	if rec.Code != 200 || json.Unmarshal(rec.Body.Bytes(), &got) != nil {
		t.Fatal(rec.Body.String())
	}
	want := map[string]string{"onecbank": "ready", "onecodata": "not_configured", "dadata": "not_configured", "fnsopendata": "ready", "wb": "mock_ready", "ozon": "mock_ready", "csv": "ready"}
	if len(got) != len(want) {
		t.Fatalf("provider count: %d", len(got))
	}
	for _, p := range got {
		if want[p.Kind] != p.Status {
			t.Fatalf("provider: %+v", p)
		}
	}
}

func TestHTTPFailuresAndNoSensitiveEcho(t *testing.T) {
	h := (API{Store: store.NewMemory(), SyncToken: "local-operator-token"}).Handler()
	var logs bytes.Buffer
	previous := log.Writer()
	log.SetOutput(&logs)
	defer log.SetOutput(previous)
	bad := []byte("1CClientBankExchange\nСекцияДокумент=x\nНазначениеПлатежа=SUPER_SECRET\n")
	rec := upload(t, h, "one", bad)
	if rec.Code != 400 || strings.Contains(rec.Body.String(), "SUPER_SECRET") || strings.Contains(logs.String(), "SUPER_SECRET") {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
	rec = upload(t, h, "one", bytes.Repeat([]byte("x"), 5<<20))
	if rec.Code != 413 {
		t.Fatalf("want 413, got %d", rec.Code)
	}
	rec = httptest.NewRecorder()
	request := httptest.NewRequest("POST", "/v1/import/onec-bank", io.NopCloser(strings.NewReader("bad")))
	request.Header.Set("Authorization", "Bearer local-operator-token")
	h.ServeHTTP(rec, request)
	if rec.Code != 400 {
		t.Fatal(rec.Code)
	}
	unauthorized := httptest.NewRecorder()
	h.ServeHTTP(unauthorized, httptest.NewRequest("GET", "/v1/batches/one", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatal("financial history must require operator token")
	}
}

func TestOneCODataSyncRequiresTokenAndDeduplicates(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u, p, ok := r.BasicAuth()
		if !ok || u != "reader" || p != "secret" {
			w.WriteHeader(401)
			return
		}
		_, _ = w.Write([]byte(`{"value":[{"Ref_Key":"ref-1","Number":"1","Date":"2026-10-20","ExecutionDate":"2026-10-20","Amount":12.34,"Posted":true,"Account_Key":"bank-account-1"}]}`))
	}))
	defer upstream.Close()
	cfg, err := onecodata.LoadConfig("../../testdata/onec_odata_mock.json")
	if err != nil {
		t.Fatal(err)
	}
	cfg.BaseURL = upstream.URL + "/odata/standard.odata/"
	cfg.Collections = cfg.Collections[:1]
	h := (API{Store: store.NewMemory(), OneCConfig: &cfg, OneCClient: onecodata.Client{Username: "reader", Password: "secret"}, SyncToken: "local-operator-token"}).Handler()
	request := func(token string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/v1/sync/onec-odata", nil)
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, r)
		return rec
	}
	if rec := request(""); rec.Code != 401 {
		t.Fatalf("without token: %d", rec.Code)
	}
	for n, accepted := range []int{1, 0} {
		rec := request("local-operator-token")
		var batch contracts.ImportBatch
		if rec.Code != 200 || json.Unmarshal(rec.Body.Bytes(), &batch) != nil || batch.Stats.Accepted != accepted {
			t.Fatalf("request %d: %d %s", n, rec.Code, rec.Body.String())
		}
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "/v1/providers", nil))
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"kind":"onecodata","mode":"pull","status":"ready"`) {
		t.Fatal(rec.Body.String())
	}
}

func TestDaDataEnrichmentRequiresToken(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"suggestions":[{"data":{"inn":"7707083893","ogrn":"1027700132195","type":"LEGAL","name":{"short_with_opf":"ПАО СБЕРБАНК"},"state":{"status":"ACTIVE"}}}]}`))
	}))
	defer upstream.Close()
	client := dadata.Client{Token: "api-secret", Endpoint: upstream.URL}
	h := (API{Store: store.NewMemory(), DaDataClient: &client, SyncToken: "local-token"}).Handler()
	request := func(token, body string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/v1/enrich/dadata-party", strings.NewReader(body))
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, r)
		return rec
	}
	if rec := request("", `{"inn":"7707083893"}`); rec.Code != 401 {
		t.Fatal(rec.Code)
	}
	if rec := request("local-token", `{"inn":"bad"}`); rec.Code != 400 {
		t.Fatal(rec.Code)
	}
	rec := request("local-token", `{"inn":"7707083893"}`)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"source_kind":"dadata"`) || !strings.Contains(rec.Body.String(), `"status":"ACTIVE"`) {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
	status := httptest.NewRecorder()
	h.ServeHTTP(status, httptest.NewRequest("GET", "/v1/providers", nil))
	if !strings.Contains(status.Body.String(), `"kind":"dadata","mode":"lookup","status":"ready"`) {
		t.Fatal(status.Body.String())
	}
}
