// Package forecast собирает прогноз остатка из компонент. Владелец: Бэк 2.
//
//	баланс(t) = остаток сегодня
//	          + Σ детерминированные компоненты (регулярные, налоги, план)  ← Go
//	          + стохастическая часть (пути из ML-сервиса)                 ← Python
//
// Детерминированная часть объясняет разрыв; стохастическая даёт коридор
// и вероятность. Если ML недоступен, Assembler берёт Fallback.
package forecast

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// ComponentFlow — одна детерминированная строка прогноза: «ЕНП 28-го −280к».
type ComponentFlow struct {
	Date   time.Time
	Key    string // "salary", "tax", "rent", "event:<id>", ...
	Title  string
	Amount domain.Money // со знаком
	Source domain.SourceKind
}

type ModelInfo struct {
	Name        string
	Description string
	IsDefault   bool
}

type StochasticRequest struct {
	CompanyID string
	Industry  string
	Model     string // "auto" или имя модели
	History   []domain.DailyFlow
	Horizon   int
	NPaths    int
	Seed      int64
	// Обученный ML включает регулярные платежи, исключает own_transfer/owner_loan.
	FlowScope string
}

// StochasticForecast — пути стохастической части: Inflow[path][day].
type StochasticForecast struct {
	ModelUsed     string
	Dates         []time.Time
	Inflow        [][]float64
	Outflow       [][]float64
	LowConfidence bool
	ModelVersion  string
	FlowScope     string
	Warnings      []string
	FallbackUsed  bool
}

// StochasticForecaster — то, что умеет ML-сервис (gRPC-клиент) и
// встроенный фолбэк.
type StochasticForecaster interface {
	Forecast(ctx context.Context, req StochasticRequest) (StochasticForecast, error)
	Models(ctx context.Context) ([]ModelInfo, error)
}

type Input struct {
	AsOf           time.Time // последний день факта
	OpeningBalance domain.Money
	Deterministic  []ComponentFlow
	Stochastic     StochasticRequest
}

// Result — компоненты прогноза. Сценарии меняют компоненты и вызывают
// Recompute, ML при этом заново не вызывается.
type Result struct {
	AsOf           time.Time
	OpeningBalance domain.Money
	Dates          []time.Time
	Deterministic  []ComponentFlow
	Stochastic     StochasticForecast
	// Balances[path][day] — остаток на конец дня.
	Balances [][]float64
}

type Assembler struct {
	Primary  StochasticForecaster // ML-сервис; может быть nil
	Fallback StochasticForecaster
	Timeout  time.Duration
	Log      *slog.Logger
}

func (a Assembler) Build(ctx context.Context, in Input) (Result, error) {
	if in.Stochastic.Horizon <= 0 || in.Stochastic.NPaths <= 0 {
		return Result{}, errors.New("forecast: horizon and n_paths must be positive")
	}
	sf, err := a.stochastic(ctx, in.Stochastic)
	if err != nil {
		return Result{}, err
	}
	res := Result{
		AsOf:           domain.Day(in.AsOf),
		OpeningBalance: in.OpeningBalance,
		Deterministic:  in.Deterministic,
		Stochastic:     sf,
	}
	res.Dates = make([]time.Time, in.Stochastic.Horizon)
	for i := range res.Dates {
		res.Dates[i] = res.AsOf.AddDate(0, 0, i+1)
	}
	if err := res.Recompute(); err != nil {
		return Result{}, err
	}
	return res, nil
}

func (a Assembler) stochastic(ctx context.Context, req StochasticRequest) (StochasticForecast, error) {
	if a.Primary != nil {
		pctx, cancel := context.WithTimeout(ctx, a.timeout())
		sf, err := a.Primary.Forecast(pctx, req)
		cancel()
		if err == nil {
			return sf, nil
		}
		if a.Log != nil {
			a.Log.Warn("ml forecast failed, using fallback", "company_id", req.CompanyID, "err", err)
		}
	}
	if a.Fallback == nil {
		return StochasticForecast{}, errors.New("forecast: no forecaster available")
	}
	return a.Fallback.Forecast(ctx, req)
}

func (a Assembler) timeout() time.Duration {
	if a.Timeout > 0 {
		return a.Timeout
	}
	return 5 * time.Second
}

// Recompute пересчитывает Balances из компонент.
func (r *Result) Recompute() error {
	h := len(r.Dates)
	sf := r.Stochastic
	if len(sf.Inflow) == 0 || len(sf.Inflow) != len(sf.Outflow) {
		return fmt.Errorf("forecast: bad stochastic paths: %d in, %d out", len(sf.Inflow), len(sf.Outflow))
	}
	det := r.DeterministicByDay()
	r.Balances = make([][]float64, len(sf.Inflow))
	for p := range sf.Inflow {
		if len(sf.Inflow[p]) < h || len(sf.Outflow[p]) < h {
			return fmt.Errorf("forecast: path %d shorter than horizon %d", p, h)
		}
		bal := r.OpeningBalance.Float()
		row := make([]float64, h)
		for d := 0; d < h; d++ {
			bal += det[d] + sf.Inflow[p][d] - sf.Outflow[p][d]
			row[d] = bal
		}
		r.Balances[p] = row
	}
	return nil
}

// DeterministicByDay — сумма детерминированных компонент по дням горизонта.
func (r Result) DeterministicByDay() []float64 {
	out := make([]float64, len(r.Dates))
	for _, c := range r.Deterministic {
		if d := r.DayIndex(c.Date); d >= 0 {
			out[d] += c.Amount.Float()
		}
	}
	return out
}

// DayIndex — индекс дня в горизонте или −1.
func (r Result) DayIndex(t time.Time) int {
	if len(r.Dates) == 0 {
		return -1
	}
	d := int(domain.Day(t).Sub(r.Dates[0]).Hours() / 24)
	if d < 0 || d >= len(r.Dates) {
		return -1
	}
	return d
}

// Quantile остатка по дням, q в [0,1].
func (r Result) Quantile(q float64) []float64 {
	out := make([]float64, len(r.Dates))
	col := make([]float64, len(r.Balances))
	for d := range out {
		for p := range r.Balances {
			col[p] = r.Balances[p][d]
		}
		out[d] = quantile(col, q)
	}
	return out
}

func quantile(xs []float64, q float64) float64 {
	if len(xs) == 0 {
		return 0
	}
	s := append([]float64(nil), xs...)
	sort.Float64s(s)
	pos := q * float64(len(s)-1)
	lo := int(pos)
	if lo >= len(s)-1 {
		return s[len(s)-1]
	}
	frac := pos - float64(lo)
	return s[lo]*(1-frac) + s[lo+1]*frac
}
