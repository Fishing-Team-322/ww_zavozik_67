package wb

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestFetchFinancialRows(t *testing.T) {
	requests := 0
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		if r.Method != http.MethodPost || r.Header.Get("Authorization") != "secret" {
			t.Errorf("wrong auth/method")
			w.WriteHeader(401)
			return
		}
		var body struct {
			RRDID int64 `json:"rrdId"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		if body.RRDID == 0 {
			w.Write([]byte(`[{"reportId":44,"rrdId":1,"currency":"RUB","docTypeName":"Продажа","forPay":"100.05","acquiringFee":"2.01","deliveryRub":"5.00"},{"reportId":44,"rrdId":2,"currency":"RUB","docTypeName":"Возврат","forPay":"-30.00"}]`))
			return
		}
		if body.RRDID != 2 {
			t.Errorf("cursor=%d", body.RRDID)
		}
		w.WriteHeader(204)
	}))
	defer s.Close()
	got, err := (Client{Token: "secret", EndpointURL: s.URL}).Fetch(context.Background(), "2026-10-01", "2026-10-07")
	if err != nil || requests != 2 || len(got) != 2 {
		t.Fatalf("got=%+v requests=%d err=%v", got, requests, err)
	}
	if got[0].AmountKopecks != 10005 || got[0].AcquiringKopecks != 201 || got[0].DeliveryKopecks != 500 || got[1].AmountKopecks != -3000 || got[1].Category != "return" || got[0].ForecastEligible {
		t.Fatalf("wrong classification: %+v", got)
	}
}

func TestLimiterHonorsCancellation(t *testing.T) {
	l := &Limiter{}
	if err := l.Wait(context.Background(), time.Second); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	if err := l.Wait(ctx, time.Second); err == nil {
		t.Fatal("rate limiter ignored context")
	}
}

func TestFetchErrors(t *testing.T) {
	for _, status := range []int{401, 403, 429, 500} {
		s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(status); w.Write([]byte(`secret`)) }))
		_, err := (Client{Token: "secret", EndpointURL: s.URL}).Fetch(context.Background(), "2026-10-01", "2026-10-02")
		s.Close()
		if err == nil || err.Error() == "secret" {
			t.Fatalf("status %d err %v", status, err)
		}
	}
	if _, err := (Client{}).Fetch(context.Background(), "2026-10-01", "2026-10-02"); err == nil {
		t.Fatal("missing token accepted")
	}
}
