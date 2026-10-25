package httpapi_test

import (
	"context"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

type backtestHistorySpy struct {
	auditFlatML
	request forecast.StochasticRequest
}

func (s *backtestHistorySpy) Forecast(ctx context.Context, r forecast.StochasticRequest) (forecast.StochasticForecast, error) {
	s.request = r
	return s.auditFlatML.Forecast(ctx, r)
}

func TestHistoricalBacktestWithholdsFutureOperationsAndDoesNotBackdateSnapshots(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	spy := &backtestHistorySpy{}
	s.ML = spy
	var before, after int
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM forecast_runs WHERE company_id=$1", cid).Scan(&before); err != nil {
		t.Fatal(err)
	}
	report := auditCall(t, h, token, "GET", "/v1/companies/"+cid+"/plan-fact/backtest", nil, 200)
	if report["kind"] != "retrospective_holdout" || report["as_of"] != "2026-09-23" || len(report["points"].([]any)) != 30 {
		t.Fatal(report)
	}
	for _, day := range spy.request.History {
		if day.Date.Format("2006-01-02") > "2026-09-23" {
			t.Fatal("holdout history leakage", day)
		}
	}
	for _, op := range spy.request.Transactions {
		if op.Date.Format("2006-01-02") > "2026-09-23" {
			t.Fatal("holdout transaction leakage", op)
		}
	}
	if spy.request.Horizon != 30 || len(spy.request.History) < 60 || report["withheld_operations"].(float64) == 0 || report["computed_at"] == nil || report["history_sha256"] == report["withheld_sha256"] {
		t.Fatal(report)
	}
	if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM forecast_runs WHERE company_id=$1", cid).Scan(&after); err != nil {
		t.Fatal(err)
	}
	if before != after {
		t.Fatal("retrospective check forged a previously issued forecast")
	}
}

func TestHistoricalBacktestScoresOnlyExplicitNonConflictingDailyBalances(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	s.ML = &backtestHistorySpy{}
	ctx := context.Background()
	if _, err := h.db.Pool.Exec(ctx, "UPDATE operations SET balance_eod=NULL WHERE company_id=$1 AND op_date>'2026-09-23' AND op_date<'2026-10-23'", cid); err != nil {
		t.Fatal(err)
	}
	path := "/v1/companies/" + cid + "/plan-fact/backtest"
	report := auditCall(t, h, token, "GET", path, nil, 200)
	if report["samples"] != float64(1) || report["excluded_days"] != float64(29) {
		t.Fatal("carried empty days became observed truth", report)
	}
	for _, item := range report["points"].([]any) {
		p := item.(map[string]any)
		if p["date"] != "2026-10-23" && (p["actual"] != nil || p["absolute_error"] != nil) {
			t.Fatal("unknown truth invented", p)
		}
	}
	if _, err := h.db.Pool.Exec(ctx, "UPDATE operations SET balance_eod=CASE WHEN direction='in' THEN 100000 ELSE 200000 END WHERE company_id=$1 AND op_date='2026-10-23'", cid); err != nil {
		t.Fatal(err)
	}
	report = auditCall(t, h, token, "GET", path, nil, 200)
	if report["samples"] != float64(0) || report["excluded_days"] != float64(30) || report["mean_absolute_error"] != nil {
		t.Fatal("conflicting anchors were scored", report)
	}
}
