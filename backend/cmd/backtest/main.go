// Command backtest — бэктест прогноза остатка на датасете кейса со
// скользящими точками старта. Гоняет тот же пайплайн, что прод.
//
//	go run ./cmd/backtest -data ../cashflow_dataset_participants/statements -out backtest.csv
//	go run ./cmd/backtest -data ... -ml localhost:50051 -model auto
//
// Результат — CSV по (компания, точка старта, горизонт); метрики и графики
// строим в ml/eval. Владелец: Бэк 2, метрики согласует тимлид.
//
// TODO(Бэк 2): детерминированные компоненты (recurring + events), метрики
// по разрывам (precision/recall, lead time), Parquet вместо CSV.
package main

import (
	"context"
	"encoding/csv"
	"flag"
	"fmt"
	"log/slog"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/dataset"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/ingest"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/logging"
)

func main() {
	var (
		dataDir   = flag.String("data", "../cashflow_dataset_participants/statements", "каталог statements/*.csv")
		companies = flag.String("companies", "", "список id через запятую (пусто — все)")
		mlAddr    = flag.String("ml", "", "адрес ML-сервиса; пусто — встроенный naive")
		model     = flag.String("model", "auto", "модель ML-сервиса")
		horizon   = flag.Int("horizon", 30, "горизонт, дней")
		origins   = flag.Int("origins", 6, "сколько точек старта на компанию")
		step      = flag.Int("step", 30, "шаг между точками старта, дней")
		minHist   = flag.Int("min-history", 56, "минимум дней истории до точки старта")
		paths     = flag.Int("paths", 200, "число путей")
		outPath   = flag.String("out", "backtest.csv", "куда писать результаты")
	)
	flag.Parse()
	log := logging.New("info")
	ctx := context.Background()

	asm := forecast.Assembler{Fallback: forecast.SeasonalNaive{}, Log: log, Timeout: 30 * time.Second}
	if *mlAddr != "" {
		ml, err := forecast.DialML(*mlAddr)
		if err != nil {
			fatal(log, err)
		}
		defer ml.Close()
		asm.Primary = ml
	}

	files, err := dataset.Files(*dataDir, splitIDs(*companies))
	if err != nil || len(files) == 0 {
		fatal(log, fmt.Errorf("no statements in %s: %v", *dataDir, err))
	}
	if err := os.MkdirAll(filepath.Dir(*outPath), 0o755); err != nil {
		fatal(log, err)
	}
	out, err := os.Create(*outPath)
	if err != nil {
		fatal(log, err)
	}
	defer out.Close()
	w := csv.NewWriter(out)
	defer w.Flush()
	_ = w.Write([]string{"company_id", "as_of", "h", "model", "low_confidence", "actual", "p10", "p50", "p90"})

	stats := map[int]*acc{7: {}, 14: {}, 30: {}}
	cat := categorize.Chain{Steps: []categorize.Categorizer{categorize.DefaultRules}, Threshold: 0.5}
	runs := 0

	for _, f := range files {
		c, err := dataset.Load(ctx, f, cat)
		if err != nil {
			fatal(log, err)
		}
		if len(c.Ops) == 0 {
			continue
		}
		first, last := c.Ops[0].Date, c.Ops[len(c.Ops)-1].Date
		flows := ingest.DailyFlows(c.Ops, first, last, dataset.NotInternal)
		dataset.FillBalance(flows)

		for k := 0; k < *origins; k++ {
			end := len(flows) - 1 - k**step
			o := end - *horizon // индекс дня as_of
			if o < *minHist || !usable(flows[o-*minHist+1:end+1]) {
				continue
			}
			res, err := asm.Build(ctx, forecast.Input{
				AsOf:           flows[o].Date,
				OpeningBalance: *flows[o].Balance,
				Stochastic: forecast.StochasticRequest{
					CompanyID: c.ID, Model: *model, History: flows[:o+1],
					Horizon: *horizon, NPaths: *paths, Seed: int64(o + 1),
				},
			})
			if err != nil {
				fatal(log, err)
			}
			runs++
			p10, p50, p90 := res.Quantile(0.1), res.Quantile(0.5), res.Quantile(0.9)
			for h := 1; h <= *horizon; h++ {
				actual := flows[o+h].Balance.Float()
				_ = w.Write([]string{c.ID, flows[o].Date.Format(domain.DateLayout), strconv.Itoa(h),
					res.Stochastic.ModelUsed, strconv.FormatBool(res.Stochastic.LowConfidence),
					num(actual), num(p10[h-1]), num(p50[h-1]), num(p90[h-1])})
				if a, ok := stats[h]; ok {
					a.add(actual, p10[h-1], p50[h-1], p90[h-1])
				}
			}
		}
	}

	fmt.Printf("companies: %d, forecast runs: %d, results: %s\n", len(files), runs, *outPath)
	for _, h := range []int{7, 14, 30} {
		if h <= *horizon {
			fmt.Printf("h=%-2d  MAE=%12.0f  WAPE=%5.1f%%  coverage p10-p90=%5.1f%%\n", h, stats[h].mae(), stats[h].wape()*100, stats[h].coverage()*100)
		}
	}
}

// usable — в окне нет пропусков выписки и остаток известен.
func usable(win []domain.DailyFlow) bool {
	for _, f := range win {
		if f.Missing || f.Balance == nil {
			return false
		}
	}
	return true
}

type acc struct{ n, absErr, absAct, covered float64 }

func (a *acc) add(actual, p10, p50, p90 float64) {
	a.n++
	a.absErr += math.Abs(actual - p50)
	a.absAct += math.Abs(actual)
	if actual >= p10 && actual <= p90 {
		a.covered++
	}
}
func (a *acc) mae() float64      { return a.absErr / math.Max(a.n, 1) }
func (a *acc) wape() float64     { return a.absErr / math.Max(a.absAct, 1) }
func (a *acc) coverage() float64 { return a.covered / math.Max(a.n, 1) }

func num(x float64) string { return strconv.FormatFloat(x, 'f', 2, 64) }

func splitIDs(s string) []string {
	if s == "" {
		return nil
	}
	return strings.Split(s, ",")
}

func fatal(log *slog.Logger, err error) {
	log.Error("backtest failed", "err", err)
	os.Exit(1)
}
