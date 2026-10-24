// Command export выгружает дневные потоки компаний для обучения и
// экспериментов в ml/: та же нормализация и категоризация, что в проде.
//
//	go run ./cmd/export -data ../cashflow_dataset_participants/statements -out ../ml/data/flows.csv
//
// Колонки: company_id, industry, date,
// inflow, outflow — потоки бизнеса (без своих переводов и займов учредителя),
// missing — день в пропуске выписки, balance — остаток на конец дня,
// cat_<категория> — сумма за день по категории со знаком (+ приход, − расход),
// включая внутренние (cat_own_transfer, cat_owner_loan).
package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"io"
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
	companiesPath := flag.String("companies-file", "", "companies.csv для колонки industry (по умолчанию ../companies.csv рядом с -data)")
	companies := flag.String("companies", "", "список id через запятую (пусто — все)")
	outPath := flag.String("out", "flows.csv", "куда писать")
	flag.Parse()
	ctx := context.Background()

	if *companiesPath == "" {
		*companiesPath = filepath.Join(filepath.Dir(filepath.Clean(*dataDir)), "companies.csv")
	}
	industries, err := loadIndustries(*companiesPath)
	if err != nil {
		fail(err)
	}

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

	header := []string{"company_id", "industry", "date", "inflow", "outflow", "missing", "balance"}
	header = append(header, "missing_known_on")
	for _, c := range domain.AllCategories {
		header = append(header, "cat_"+string(c))
	}
	_ = w.Write(header)

	cat := categorize.Chain{Steps: []categorize.Categorizer{categorize.DefaultRules}, Threshold: 0.5}
	rows := 0
	quality := map[string]any{}
	for _, f := range files {
		c, err := dataset.Load(ctx, f, cat)
		if err != nil {
			fail(err)
		}
		if len(c.Ops) == 0 {
			continue
		}
		first, last := c.Ops[0].Date, c.Ops[len(c.Ops)-1].Date
		flows, detected := ingest.DailyFlowsWithDetection(c.Ops, first, last, dataset.NotInternal)
		dataset.FillBalance(flows)
		missingDays := 0
		for _, fl := range flows {
			if fl.Missing {
				missingDays++
			}
		}
		quality[c.ID] = map[string]any{"duplicates_removed": c.Quality.Removed, "duplicate_candidates_retained": c.Quality.Unconfirmed, "missing_days": missingDays}

		for i, fl := range flows {
			bal := ""
			if fl.Balance != nil {
				bal = fl.Balance.String()
			}
			rec := []string{c.ID, industries[c.ID], fl.Date.Format(domain.DateLayout), fl.Inflow.String(),
				fl.Outflow.String(), strconv.FormatBool(fl.Missing), bal}
			known := ""
			if !detected[i].IsZero() {
				known = detected[i].Format(domain.DateLayout)
			}
			rec = append(rec, known)
			for _, c := range domain.AllCategories {
				rec = append(rec, fl.ByCategory[c].String())
			}
			_ = w.Write(rec)
			rows++
		}
	}
	w.Flush()
	if err := w.Error(); err != nil {
		fail(err)
	}
	meta, err := json.MarshalIndent(map[string]any{"schema_version": 2, "target": "business_without_internal_transfers", "companies": quality}, "", "  ")
	if err != nil {
		fail(err)
	}
	if err := os.WriteFile(*outPath+".quality.json", meta, 0644); err != nil {
		fail(err)
	}
	fmt.Printf("companies: %d, rows: %d, out: %s\n", len(files), rows, *outPath)
}

// loadIndustries читает companies.csv датасета кейса: company_id → industry.
func loadIndustries(path string) (map[string]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	r := csv.NewReader(f)
	r.Comma = ';'
	head, err := r.Read()
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	idCol, indCol := -1, -1
	for i, h := range head {
		switch strings.TrimPrefix(h, "\uFEFF") {
		case "company_id":
			idCol = i
		case "industry":
			indCol = i
		}
	}
	if idCol < 0 || indCol < 0 {
		return nil, fmt.Errorf("%s: no company_id/industry columns", path)
	}
	out := map[string]string{}
	for {
		rec, err := r.Read()
		if err == io.EOF {
			return out, nil
		}
		if err != nil {
			return nil, fmt.Errorf("%s: %w", path, err)
		}
		out[rec[idCol]] = rec[indCol]
	}
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, "export:", err)
	os.Exit(1)
}
