package product

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/jackc/pgx/v5"
)

// Preserve model paths beyond the visible horizon. New bank facts rebase the
// future suffix on the actual closing balance; plan edits only recompose known
// events. This is inference reuse, not training or conditioning the model on
// newly observed transaction tokens. Revisions of old facts force new inference.
type incrementalForecaster struct {
	db      *store.Postgres
	primary forecast.StochasticForecaster
}

func (f incrementalForecaster) Models(ctx context.Context) ([]forecast.ModelInfo, error) {
	if f.primary == nil {
		return nil, nil
	}
	return f.primary.Models(ctx)
}

func (f incrementalForecaster) Forecast(ctx context.Context, req forecast.StochasticRequest) (forecast.StochasticForecast, error) {
	if f.primary == nil {
		return forecast.StochasticForecast{}, errors.New("forecast model unavailable")
	}
	keyBytes := sha256.Sum256(store.JSON([]any{req.Model, req.Industry, req.NPaths, req.Seed, req.FlowScope}))
	key := hex.EncodeToString(keyBytes[:])
	var rawRequest, rawResult []byte
	err := f.db.Pool.QueryRow(ctx, "SELECT request,result FROM forecast_baselines WHERE company_id=$1 AND cache_key=$2 AND saved_at>now()-interval '7 days'", req.CompanyID, key).Scan(&rawRequest, &rawResult)
	if err == nil {
		var previous forecast.StochasticRequest
		var saved forecast.StochasticForecast
		if json.Unmarshal(rawRequest, &previous) == nil && json.Unmarshal(rawResult, &saved) == nil {
			if sf, ok := reuseForecastPaths(previous, req, saved); ok {
				return sf, nil
			}
		}
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return forecast.StochasticForecast{}, err
	}
	// A month of spare future paths avoids full model inference on every new
	// statement. The response returned to callers still has exactly their horizon.
	expanded := req
	expanded.Horizon += 30
	if expanded.Horizon > 366 {
		expanded.Horizon = 366
	}
	result, err := (forecast.Assembler{Primary: f.primary, Timeout: 10 * time.Second}).Build(ctx, forecast.Input{AsOf: req.History[len(req.History)-1].Date, Stochastic: expanded})
	if err != nil {
		return forecast.StochasticForecast{}, err
	}
	saved := result.Stochastic
	// Never retain a substitute sampler under a primary-model cache key.
	if !saved.FallbackUsed {
		_, err = f.db.Pool.Exec(ctx, `INSERT INTO forecast_baselines(company_id,cache_key,model,request,result) VALUES($1,$2,$3,$4,$5)
ON CONFLICT(company_id,cache_key) DO UPDATE SET model=EXCLUDED.model,request=EXCLUDED.request,result=EXCLUDED.result,saved_at=now()`, req.CompanyID, key, req.Model, store.JSON(expanded), store.JSON(saved))
		if err != nil {
			return forecast.StochasticForecast{}, err
		}
	}
	out, ok := reuseForecastPaths(expanded, req, saved)
	if !ok {
		return forecast.StochasticForecast{}, errors.New("invalid stored model paths")
	}
	out.UpdateMode = "fresh_paths"
	return out, nil
}

func reuseForecastPaths(previous, req forecast.StochasticRequest, saved forecast.StochasticForecast) (forecast.StochasticForecast, bool) {
	if len(previous.History) == 0 || len(req.History) == 0 {
		return forecast.StochasticForecast{}, false
	}
	// The application's two-year window advances with each statement. Compare
	// the overlapping model input rather than treating a dropped oldest day as
	// a change to the observed economic facts. Balances are composed by Go and
	// are not part of the model's DailyFlow input.
	dropped := int(domain.Day(req.History[0].Date).Sub(domain.Day(previous.History[0].Date)).Hours() / 24)
	if dropped < 0 || dropped >= len(previous.History) || len(req.History) < len(previous.History)-dropped {
		return forecast.StochasticForecast{}, false
	}
	overlap := len(previous.History) - dropped
	for i := 0; i < overlap; i++ {
		before, after := previous.History[dropped+i], req.History[i]
		before.Balance = nil
		after.Balance = nil
		if !bytes.Equal(store.JSON(before), store.JSON(after)) {
			return forecast.StochasticForecast{}, false
		}
	}
	oldTransactions := previous.Transactions
	for len(oldTransactions) > 0 && oldTransactions[0].Date.Before(req.History[0].Date) {
		oldTransactions = oldTransactions[1:]
	}
	if len(req.Transactions) < len(oldTransactions) || !bytes.Equal(store.JSON(oldTransactions), store.JSON(req.Transactions[:len(oldTransactions)])) {
		return forecast.StochasticForecast{}, false
	}
	oldAsOf := domain.Day(previous.History[len(previous.History)-1].Date)
	asOf := domain.Day(req.History[len(req.History)-1].Date)
	offset := int(asOf.Sub(oldAsOf).Hours() / 24)
	if offset < 0 || offset+req.Horizon > len(saved.Dates) || len(saved.Inflow) != req.NPaths || len(saved.Outflow) != req.NPaths {
		return forecast.StochasticForecast{}, false
	}
	for _, flow := range req.History[overlap:] {
		if flow.Missing {
			return forecast.StochasticForecast{}, false
		}
	}
	out := (forecast.Result{Stochastic: saved}).Clone().Stochastic
	out.Dates = out.Dates[offset : offset+req.Horizon]
	for p := range out.Inflow {
		if len(out.Inflow[p]) < offset+req.Horizon || len(out.Outflow[p]) < offset+req.Horizon {
			return forecast.StochasticForecast{}, false
		}
		out.Inflow[p] = out.Inflow[p][offset : offset+req.Horizon]
		out.Outflow[p] = out.Outflow[p][offset : offset+req.Horizon]
	}
	out.UpdateMode = "reused_paths"
	out.BaseAsOf = oldAsOf.Format(domain.DateLayout)
	if offset > 0 {
		out.UpdateMode = "updated_from_actuals"
		out.Warnings = append(out.Warnings, "future_paths_reused_with_actual_opening_balance")
	}
	return out, true
}
