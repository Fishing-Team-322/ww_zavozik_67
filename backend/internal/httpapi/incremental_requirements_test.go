package httpapi_test

import (
	"context"
	"sync/atomic"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

type countedRequirementML struct {
	calls        atomic.Int64
	transactions atomic.Int64
}

func (m *countedRequirementML) Models(context.Context) ([]forecast.ModelInfo, error) { return nil, nil }
func (m *countedRequirementML) Forecast(ctx context.Context, req forecast.StochasticRequest) (forecast.StochasticForecast, error) {
	m.calls.Add(1)
	m.transactions.Store(int64(len(req.Transactions)))
	sf, e := (auditFlatML{}).Forecast(ctx, req)
	sf.ModelVersion = "transaction-model-contract-test"
	return sf, e
}

func TestNewStatementReusesPersistedFuturePaths(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	model := &countedRequirementML{}
	s.ML = model
	first := auditForecast(t, h, token, cid)
	if first["update_mode"] != "fresh_paths" || model.calls.Load() != 1 || model.transactions.Load() != 180 {
		t.Fatal(first, model.calls.Load())
	}
	// A plan changes the forecast immediately while leaving sampled model paths intact.
	auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/invoices", product.Doc{"number": "Future income", "direction": "issued", "amount": 1000, "issued_at": "2026-10-23", "due_at": "2026-10-26"}, 201)
	if got := auditForecast(t, h, token, cid); got["update_mode"] != "reused_paths" || model.calls.Load() != 1 {
		t.Fatal(got, model.calls.Load())
	}
	// A new process has no in-memory cache; reuse must survive it.
	restarted := &product.Service{DB: h.db, ML: model, Fallback: forecast.SeasonalNaive{}}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: restarted, Log: testLogger()}).Handler()
	auditOperation(t, h, cid, "2026-10-24", "Actual client", "", 100, first["opening_balance"].(float64)+100)
	drainCase(t, restarted)
	updated := auditForecast(t, h, token, cid)
	if model.calls.Load() != 1 || updated["as_of"] != "2026-10-24" || updated["update_mode"] != "updated_from_actuals" || updated["model_as_of"] != "2026-10-23" {
		t.Fatal(updated, model.calls.Load())
	}
	if updated["opening_balance"] != first["opening_balance"].(float64)+100 {
		t.Fatal("did not use actual closing balance", updated)
	}
	// Correcting historical economic facts invalidates the frozen future.
	_, e := h.db.Pool.Exec(context.Background(), "UPDATE operations SET category='other' WHERE company_id=$1 AND direction='in' AND op_date='2026-10-20'", cid)
	if e != nil {
		t.Fatal(e)
	}
	auditForecast(t, h, token, cid)
	if model.calls.Load() != 2 {
		t.Fatal("corrected history reused obsolete paths", model.calls.Load())
	}
}
