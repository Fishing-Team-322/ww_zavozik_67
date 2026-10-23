// Command export выгружает дневные потоки компаний для обучения и
// экспериментов в ml/: та же нормализация и категоризация, что в проде.
//
//	go run ./cmd/export -data ../cashflow_dataset_participants/statements -out ../ml/data/flows.csv
//
// Колонки: company_id, date, inflow, outflow (без внутренних переводов),
// missing (день в пропуске выписки), balance (остаток на конец дня).
//
// TODO(Бэк 1): колонки по категориям и стохастическая часть
// (потоки минус регулярные платежи), Parquet.
package main

import (
	"context"
	"encoding/csv"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/dataset"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/ingest"
)

func main() {
	dataDir := flag.String("data", "../cashflow_dataset_participants/statements", "каталог statements/*.csv")
	companies := flag.String("companies", "", "список id через запятую (пусто — все)")
	outPath := flag.String("out", "flows.csv", "куда писать")
	flag.Parse()
	ctx := context.Background()

	var ids []string
	if *companies != "" {
		ids = strings.Split(*companies, ",")
	}
	files, err := dataset.Files(*dataDir, ids)
	if err != nil || len(files) == 0 {
		fail(fmt.Errorf("no statements in %s: %v", *dataDir, err))
	}
	if err := os.MkdirAll(filepath.Dir(*outPath), 0o755); err != nil {
		fail(err)
	}
	out, err := os.Create(*outPath)
	if err != nil {
		fail(err)
	}
	defer out.Close()
	w := csv.NewWriter(out)
	defer w.Flush()
	_ = w.Write([]string{"company_id", "date", "inflow", "outflow", "missing", "balance"})

	cat := categorize.Chain{Steps: []categorize.Categorizer{categorize.DefaultRules}, Threshold: 0.5}
	rows := 0
	for _, f := range files {
		c, err := dataset.Load(ctx, f, cat)
		if err != nil {
			fail(err)
		}
		if len(c.Ops) == 0 {
			continue
		}
		flows := ingest.DailyFlows(c.Ops, c.Ops[0].Date, c.Ops[len(c.Ops)-1].Date, dataset.NotInternal)
		dataset.FillBalance(flows)
		for _, fl := range flows {
			bal := ""
			if fl.Balance != nil {
				bal = fl.Balance.String()
			}
			_ = w.Write([]string{c.ID, fl.Date.Format(domain.DateLayout), fl.Inflow.String(),
				fl.Outflow.String(), strconv.FormatBool(fl.Missing), bal})
			rows++
		}
	}
	fmt.Printf("companies: %d, rows: %d, out: %s\n", len(files), rows, *outPath)
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, "export:", err)
	os.Exit(1)
}
