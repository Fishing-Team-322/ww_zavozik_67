package ozon

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func interval() (time.Time, time.Time) {
	a := time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)
	return a, a.AddDate(0, 0, 7)
}

func TestFetchTransactions(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.Header.Get("Client-Id") != "id" || r.Header.Get("Api-Key") != "secret" {
			t.Error("wrong headers")
			w.WriteHeader(401)
			return
		}
		var body struct {
			Page     int `json:"page"`
			PageSize int `json:"page_size"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		if body.PageSize != 1000 {
			t.Errorf("page_size=%d", body.PageSize)
		}
		if body.Page == 1 {
			w.Write([]byte(`{"result":{"page_count":2,"operations":[{"operation_id":11,"operation_type":"OperationAgentDeliveredToCustomer","operation_date":"2026-10-01T00:00:00Z","amount":100.05,"accruals_for_sale":120.05,"sale_commission":-20,"delivery_charge":0}]}}`))
			return
		}
		w.Write([]byte(`{"result":{"page_count":2,"operations":[{"operation_id":12,"operation_type":"ClientReturn","operation_date":"2026-10-02T00:00:00Z","amount":-30.01},{"operation_id":11,"operation_type":"OperationAgentDeliveredToCustomer","operation_date":"2026-10-01T00:00:00Z","amount":100.05}]}}`))
	}))
	defer s.Close()
	a, b := interval()
	got, err := (Client{ClientID: "id", APIKey: "secret", EndpointURL: s.URL}).Fetch(context.Background(), a, b)
	if err != nil || len(got) != 2 {
		t.Fatalf("got=%+v err=%v", got, err)
	}
	if got[0].AmountKopecks != 10005 || got[0].AccrualsKopecks != 12005 || got[0].SaleCommissionKopecks != -2000 || got[1].AmountKopecks != -3001 || got[1].Category != "return" || got[0].ForecastEligible {
		t.Fatalf("classification: %+v", got)
	}
}

func TestFetchErrors(t *testing.T) {
	a, b := interval()
	for _, status := range []int{401, 403, 429, 500} {
		s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(status); w.Write([]byte(`secret`)) }))
		_, err := (Client{ClientID: "id", APIKey: "secret", EndpointURL: s.URL}).Fetch(context.Background(), a, b)
		s.Close()
		if err == nil || err.Error() == "secret" {
			t.Fatalf("HTTP %d: %v", status, err)
		}
	}
	if _, err := (Client{}).Fetch(context.Background(), a, b); err == nil {
		t.Fatal("missing credentials accepted")
	}
	if _, err := (Client{ClientID: "id", APIKey: "secret"}).Fetch(context.Background(), a, b.AddDate(0, 2, 0)); err == nil {
		t.Fatal("large interval accepted")
	}
}
