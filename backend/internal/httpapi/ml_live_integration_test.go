package httpapi_test

import (
	"context"
	"fmt"
	"math"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

type observedML struct {
	forecast.StochasticForecaster
	calls atomic.Int64
}

func (m *observedML) Forecast(ctx context.Context, r forecast.StochasticRequest) (forecast.StochasticForecast, error) {
	m.calls.Add(1)
	return m.StochasticForecaster.Forecast(ctx, r)
}

// This test uses the real Python service and committed artifacts, not a gRPC fixture.
func TestLiveMLThroughFinancialAPI(t *testing.T) {
	addr := os.Getenv("TEST_ML_ADDR")
	if addr == "" {
		t.Skip("set TEST_ML_ADDR and TEST_DATABASE_URL for the Go/Python integration check")
	}
	h := integration(t)
	ctx := context.Background()
	owner, _ := h.register("ml-bridge@example.com")
	response := h.call("POST", "/v1/companies", `{"name":"ML bridge","legal_form":"ООО","industry":"services"}`, owner)
	status(t, response, 201)
	company := decode[product.Doc](t, response)
	cid := company["id"].(string)
	client, e := forecast.DialML(addr)
	if e != nil {
		t.Fatal(e)
	}
	defer client.Close()
	observed := &observedML{StochasticForecaster: client}
	service := &product.Service{DB: h.db, ML: forecast.NewCachedForecaster(observed, time.Minute, 16)}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: service, Log: testLogger()}).Handler()
	// Every day has explicit closing balance, including zero-flow ambiguity protection.
	balance := 100000.0
	asOf := time.Date(2026, 10, 23, 0, 0, 0, 0, time.UTC)
	for i := 119; i >= 0; i-- {
		dt := asOf.AddDate(0, 0, -i)
		in := 10000 + float64(i%7)*100
		out := 7000 + float64(i%5)*50
		if dt.Weekday() == time.Saturday || dt.Weekday() == time.Sunday {
			in, out = 0, 0
		}
		balance += in - out
		for _, row := range []struct {
			direction, category string
			amount              float64
		}{{"in", "revenue_b2b", in}, {"out", "supplier", out}} {
			_, e = h.db.Pool.Exec(ctx, `INSERT INTO operations(id,company_id,op_date,amount,direction,counterparty_name,purpose,balance_eod,category,category_method,dedup_hash,extra) VALUES($1,$2,$3,$4,$5,'Test party','Synthetic fixture',$6,$7,'rule',$1,'{"source":"upload"}')`, fmt.Sprintf("ml-%s-%d", row.direction, i), cid, dt, row.amount, row.direction, balance, row.category)
			if e != nil {
				t.Fatal(e)
			}
		}
	}
	base := "/v1/companies/" + cid
	get := func() product.Doc {
		t.Helper()
		r := h.call("GET", base+"/forecast", "", owner)
		status(t, r, 200)
		return decode[product.Doc](t, r)
	}
	first := get()
	if first["fallback_used"] != false || first["model_version"] == "" || first["flow_scope"] != forecast.BusinessFlowScope {
		t.Fatalf("expected real model metadata: model=%v fallback=%v warnings=%v", first["model_used"], first["fallback_used"], first["warnings"])
	}
	if len(first["points"].([]any)) != 30 {
		t.Fatal("wrong horizon")
	}
	get()
	if observed.calls.Load() != 1 {
		t.Fatal("identical history did not reuse ML paths")
	}
	dt := asOf.AddDate(0, 0, 1).Format(domain.DateLayout)
	r := h.call("POST", base+"/events", fmt.Sprintf(`{"title":"Additional expense","date":%q,"amount":1000000,"direction":"out"}`, dt), owner)
	status(t, r, 201)
	second := get()
	if observed.calls.Load() != 1 {
		t.Fatal("an additional event unnecessarily recomputed ML")
	}
	before := first["points"].([]any)
	after := second["points"].([]any)
	for i := range before {
		a := before[i].(map[string]any)["p50"].(float64)
		b := after[i].(map[string]any)["p50"].(float64)
		if math.Abs(a-b-1000000) > .05 {
			t.Fatalf("event missing or counted twice on day %d: %v -> %v", i, a, b)
		}
	}
	r = h.call("POST", base+"/scenarios/preview", `{"steps":[{"kind":"scale_revenue","factor":0.8}]}`, owner)
	status(t, r, 200)
	if observed.calls.Load() != 1 {
		t.Fatal("scenario changed the underlying cached paths")
	}
	r = h.call("GET", base+"/forecast?model=seasonal_naive", "", owner)
	status(t, r, 200)
	if observed.calls.Load() != 2 {
		t.Fatal("model selection did not invalidate cache")
	}
}
