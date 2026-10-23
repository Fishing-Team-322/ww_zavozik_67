package forecast

import (
	"context"
	"math/rand/v2"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// SeasonalNaive — встроенный фолбэк: для каждого дня горизонта берёт
// случайный день с тем же днём недели из последних Weeks недель истории
// (бутстрап). Тот же алгоритм, что ml/zavozik_ml/forecasters/naive.py.
type SeasonalNaive struct {
	Weeks int // по умолчанию 8
}

const (
	NaiveName        = "builtin_seasonal_naive"
	minConfidentDays = 28
)

func (s SeasonalNaive) Models(context.Context) ([]ModelInfo, error) {
	return []ModelInfo{{Name: NaiveName, Description: "Встроенный фолбэк: бутстрап по дню недели за последние недели"}}, nil
}

func (s SeasonalNaive) Forecast(_ context.Context, req StochasticRequest) (StochasticForecast, error) {
	weeks := s.Weeks
	if weeks <= 0 {
		weeks = 8
	}
	seed := uint64(req.Seed)
	if seed == 0 {
		seed = rand.Uint64()
	}
	rng := rand.New(rand.NewPCG(seed, seed^0x9e3779b97f4a7c15))

	// Пулы наблюдений по дню недели из последнего окна без пропусков.
	var pools [7][]domain.DailyFlow
	valid := 0
	start := len(req.History) - weeks*7
	if start < 0 {
		start = 0
	}
	for _, f := range req.History[start:] {
		if f.Missing {
			continue
		}
		valid++
		wd := f.Date.Weekday()
		pools[wd] = append(pools[wd], f)
	}

	var last time.Time
	if n := len(req.History); n > 0 {
		last = domain.Day(req.History[n-1].Date)
	}
	out := StochasticForecast{
		ModelUsed:     NaiveName,
		Dates:         make([]time.Time, req.Horizon),
		Inflow:        make([][]float64, req.NPaths),
		Outflow:       make([][]float64, req.NPaths),
		LowConfidence: valid < minConfidentDays,
	}
	for d := range out.Dates {
		out.Dates[d] = last.AddDate(0, 0, d+1)
	}
	for p := 0; p < req.NPaths; p++ {
		in := make([]float64, req.Horizon)
		outf := make([]float64, req.Horizon)
		for d, date := range out.Dates {
			pool := pools[date.Weekday()]
			if len(pool) == 0 {
				continue
			}
			f := pool[rng.IntN(len(pool))]
			in[d], outf[d] = f.Inflow.Float(), f.Outflow.Float()
		}
		out.Inflow[p], out.Outflow[p] = in, outf
	}
	return out, nil
}
