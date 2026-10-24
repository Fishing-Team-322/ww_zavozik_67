package httpapi

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/ozon"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/wb"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func TestMarketplaceSyncSeparateFromBankFacts(t *testing.T) {
	wbServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "wb-secret" {
			t.Error("WB auth")
			w.WriteHeader(401)
			return
		}
		if strings.Contains(readBody(r), `"rrdId":0`) {
			w.Write([]byte(`[{"reportId":1,"rrdId":1,"currency":"RUB","docTypeName":"Продажа","forPay":"100.00"}]`))
			return
		}
		w.WriteHeader(204)
	}))
	defer wbServer.Close()
	ozonServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Client-Id") != "oz-id" || r.Header.Get("Api-Key") != "oz-secret" {
			t.Error("Ozon auth")
			w.WriteHeader(401)
			return
		}
		w.Write([]byte(`{"result":{"page_count":1,"operations":[{"operation_id":2,"operation_type":"ClientReturn","operation_date":"2026-10-02T00:00:00Z","amount":-30.50}]}}`))
	}))
	defer ozonServer.Close()
	a := API{Store: store.NewMemory(), CompanyID: "demo-company", SyncToken: "operator", WBClient: &wb.Client{Token: "wb-secret", EndpointURL: wbServer.URL}, OzonClient: &ozon.Client{ClientID: "oz-id", APIKey: "oz-secret", EndpointURL: ozonServer.URL}}
	h := a.Handler()
	call := func(path string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", path, strings.NewReader(`{"from":"2026-10-01","to":"2026-10-07"}`))
		r.Header.Set("Authorization", "Bearer operator")
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w
	}
	if rec := call("/v1/sync/wb-finance"); rec.Code != 200 || !strings.Contains(rec.Body.String(), `"changed":1`) {
		t.Fatalf("WB: %d %s", rec.Code, rec.Body.String())
	}
	if rec := call("/v1/sync/wb-finance"); rec.Code != 200 || !strings.Contains(rec.Body.String(), `"duplicates":1`) {
		t.Fatalf("WB duplicate: %d %s", rec.Code, rec.Body.String())
	}
	if rec := call("/v1/sync/ozon-finance"); rec.Code != 200 || !strings.Contains(rec.Body.String(), `"changed":1`) {
		t.Fatalf("Ozon: %d %s", rec.Code, rec.Body.String())
	}
	request := httptest.NewRequest("GET", "/v1/marketplace-entries/demo-company", nil)
	request.Header.Set("Authorization", "Bearer operator")
	response := httptest.NewRecorder()
	h.ServeHTTP(response, request)
	if response.Code != 200 || !strings.Contains(response.Body.String(), `"amount_kopecks":-3050`) || !strings.Contains(response.Body.String(), `"forecast_eligible":false`) {
		t.Fatalf("marketplace entries: %d %s", response.Code, response.Body.String())
	}
	request = httptest.NewRequest("GET", "/v1/operations/demo-company", nil)
	request.Header.Set("Authorization", "Bearer operator")
	response = httptest.NewRecorder()
	h.ServeHTTP(response, request)
	if response.Code != 200 || !strings.Contains(response.Body.String(), `"operations":[]`) {
		t.Fatalf("marketplace became bank fact: %s", response.Body.String())
	}
}

func readBody(r *http.Request) string { b, _ := io.ReadAll(r.Body); return string(b) }
