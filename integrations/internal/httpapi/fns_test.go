package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func TestRegistryHTTPPostgresIsolation(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}
	db, e := store.OpenPostgres(context.Background(), dsn)
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	company := fmt.Sprintf("http-fns-%d", time.Now().UnixNano())
	api := API{Store: db, CompanyID: company, SyncToken: "test-token"}
	h := api.Handler()
	request := func(method, url string, body []byte, contentType, token string) *httptest.ResponseRecorder {
		t.Helper()
		req := httptest.NewRequest(method, url, bytes.NewReader(body))
		if contentType != "" {
			req.Header.Set("Content-Type", contentType)
		}
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, req)
		return w
	}
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	_ = writer.WriteField("company_id", company)
	file, e := writer.CreateFormFile("file", "test.xml")
	if e != nil {
		t.Fatal(e)
	}
	_, _ = file.Write([]byte(`<EGRUL ДатаВыг="2026-10-24"><СвЮЛ ИНН="9723161623" ОГРН="1234567890127" ДатаВып="2026-10-24"><СвНаимЮЛ НаимЮЛПолн="Тестовая компания"/></СвЮЛ></EGRUL>`))
	_ = writer.Close()
	if w := request("POST", "/v1/fns/xml/import", body.Bytes(), writer.FormDataContentType(), ""); w.Code != 401 {
		t.Fatalf("auth: %d", w.Code)
	}
	badCompany := bytes.Replace(body.Bytes(), []byte(company), []byte("other-company"), 1)
	if w := request("POST", "/v1/fns/xml/import", badCompany, writer.FormDataContentType(), "test-token"); w.Code != 403 {
		t.Fatalf("company scope: %d", w.Code)
	}
	pdfData, e := os.ReadFile("../providers/fnsregistry/testdata/synthetic_egrul.pdf")
	if e != nil {
		t.Fatal(e)
	}
	var pdfBody bytes.Buffer
	pdfWriter := multipart.NewWriter(&pdfBody)
	_ = pdfWriter.WriteField("company_id", company)
	pdfFile, e := pdfWriter.CreateFormFile("file", "extract.pdf")
	if e != nil {
		t.Fatal(e)
	}
	_, _ = pdfFile.Write(pdfData)
	_ = pdfWriter.Close()
	if w := request("POST", "/v1/fns/egrul/import", pdfBody.Bytes(), pdfWriter.FormDataContentType(), "test-token"); w.Code != 200 {
		t.Fatalf("PDF import: %d %s", w.Code, w.Body.String())
	}
	if w := request("POST", "/v1/fns/egrip/import", pdfBody.Bytes(), pdfWriter.FormDataContentType(), "test-token"); w.Code != 422 {
		t.Fatalf("wrong PDF route: %d", w.Code)
	}
	if w := request("POST", "/v1/fns/xml/import", body.Bytes(), writer.FormDataContentType(), "test-token"); w.Code != 200 {
		t.Fatalf("import: %d %s", w.Code, w.Body.String())
	}
	if w := request("POST", "/v1/fns/xml/import", body.Bytes(), writer.FormDataContentType(), "test-token"); w.Code != 200 || !bytes.Contains(w.Body.Bytes(), []byte(`"duplicates":1`)) {
		t.Fatalf("duplicate: %d %s", w.Code, w.Body.String())
	}
	w := request("GET", "/v1/counterparty-intelligence/9723161623", nil, "", "test-token")
	if w.Code != 200 {
		t.Fatalf("profile: %d %s", w.Code, w.Body.String())
	}
	var result map[string]json.RawMessage
	if e := json.Unmarshal(w.Body.Bytes(), &result); e != nil {
		t.Fatal(e)
	}
	if !bytes.Contains(result["profile"], []byte("Тестовая компания")) {
		t.Fatalf("profile absent: %s", w.Body.String())
	}
	if w := request("GET", "/v1/fns/counterparties/9723161623/history", nil, "", "test-token"); w.Code != 200 {
		t.Fatalf("history: %d", w.Code)
	}
	if other, e := db.GetRegistry(context.Background(), company+"-other", "9723161623"); e != nil || len(other) != 0 {
		t.Fatalf("tenant leak: %+v %v", other, e)
	}
}
