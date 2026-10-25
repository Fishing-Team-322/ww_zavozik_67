package product

import (
	"context"
	"crypto/sha256"
	"fmt"
	"math"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/dataset"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/ingest"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

// Evaluate a fixed holdout now; never backdate a forecast_run or expose the
// withheld operations, balances or current future plans to model inference.
func (s *Service) historicalBacktest(ctx context.Context, uid, cid string) (Result, error) {
	company, err := s.DB.GetCompany(ctx, uid, cid)
	if err != nil {
		return Result{}, err
	}
	rows, err := s.DB.ProductList(ctx, uid, cid, "operation")
	if err != nil {
		return Result{}, err
	}
	ops := domainOperations(rows)
	if len(ops) == 0 {
		return Result{}, platform.Fail(422, "data_required", "Загрузите выписку для проверки прогноза")
	}
	end := ops[len(ops)-1].Date
	cutoff := end.AddDate(0, 0, -30)
	prefix, withheld := []domain.Operation{}, []domain.Operation{}
	for _, op := range ops {
		if op.Date.After(cutoff) {
			withheld = append(withheld, op)
		} else {
			prefix = append(prefix, op)
		}
	}
	if len(prefix) == 0 {
		return Result{}, platform.Fail(422, "history_required", "Нужно минимум 60 дней истории до проверяемого периода в 30 дней")
	}
	history := ingest.DailyFlows(prefix, prefix[0].Date, cutoff, dataset.NotInternal)
	dataset.FillBalance(history)
	if len(history) < 60 || history[len(history)-1].Balance == nil {
		return Result{}, platform.Fail(422, "history_required", "Нужно минимум 60 дней истории и известный остаток до проверяемого периода")
	}
	if s.ML == nil {
		return Result{}, platform.Fail(503, "model_unavailable", "Модель временно недоступна; подставной прогноз не создаётся")
	}
	res, err := (forecast.Assembler{Primary: s.ML, Timeout: 15 * time.Second}).Build(ctx, forecast.Input{AsOf: cutoff, OpeningBalance: *history[len(history)-1].Balance, Stochastic: forecast.StochasticRequest{CompanyID: cid, Industry: company.Industry, Model: "auto", History: history, Transactions: observedTransactions(cid, prefix, history), Horizon: 30, NPaths: 600, Seed: 67, FlowScope: forecast.BusinessFlowScope}})
	if err != nil {
		return Result{}, platform.Fail(503, "model_unavailable", "Модель не смогла выполнить проверку; повторите расчёт позже")
	}
	actual := ingest.DailyFlows(ops, ops[0].Date, end, dataset.NotInternal)
	dataset.FillBalance(actual)
	truth := map[string]domain.DailyFlow{}
	for _, flow := range actual {
		truth[flow.Date.Format(domain.DateLayout)] = flow
	}
	q10, q50, q90 := res.Quantile(.1), res.Quantile(.5), res.Quantile(.9)
	points := []Doc{}
	totalError, covered, samples := 0.0, 0, 0
	for i, dt := range res.Dates {
		date := dt.Format(domain.DateLayout)
		point := Doc{"date": date, "forecast": money(q50[i]), "lower": money(q10[i]), "upper": money(q90[i]), "actual": nil, "absolute_error": nil}
		if flow, ok := truth[date]; ok && !flow.Missing && flow.Balance != nil {
			value := flow.Balance.Float()
			error := math.Abs(q50[i] - value)
			point["actual"], point["absolute_error"] = money(value), money(error)
			totalError += error
			samples++
			if value >= q10[i] && value <= q90[i] {
				covered++
			}
		}
		points = append(points, point)
	}
	var mae any
	if samples > 0 {
		mae = money(totalError / float64(samples))
	}
	return ok(Doc{"kind": "retrospective_holdout", "computed_at": time.Now().UTC().Format(time.RFC3339), "as_of": cutoff.Format(domain.DateLayout), "from": cutoff.AddDate(0, 0, 1).Format(domain.DateLayout), "to": end.Format(domain.DateLayout), "horizon": 30, "model_used": res.Stochastic.ModelUsed, "model_version": res.Stochastic.ModelVersion, "fallback_used": res.Stochastic.FallbackUsed, "low_confidence": res.Stochastic.LowConfidence, "warnings": res.Stochastic.Warnings, "history_days": len(history), "history_operations": len(prefix), "withheld_operations": len(withheld), "history_sha256": fmt.Sprintf("%x", sha256.Sum256(store.JSON(prefix))), "withheld_sha256": fmt.Sprintf("%x", sha256.Sum256(store.JSON(withheld))), "samples": samples, "excluded_days": 30 - samples, "mean_absolute_error": mae, "covered_days": covered, "points": points, "notice": "Ретроспективная проверка, рассчитанная сейчас: последние 30 дней не переданы модели. Будущие планы не использованы. Пересечение с исходным обучением модели неизвестно; это не независимый аудит точности."})
}
