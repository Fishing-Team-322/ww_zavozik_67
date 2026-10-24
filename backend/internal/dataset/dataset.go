// Package dataset загружает выписки датасета кейса для бэктеста и выгрузки
// в ML: парсинг, сортировка, категоризация — тот же код, что в проде.
package dataset

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/ingest"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/sources/casecsv"
)

type Company struct {
	ID      string
	Ops     []domain.Operation
	Quality ingest.DedupReport
}

// Files — statements/*.csv в dir, отфильтрованные по ids (пусто — все).
func Files(dir string, ids []string) ([]string, error) {
	files, err := filepath.Glob(filepath.Join(dir, "*.csv"))
	if err != nil {
		return nil, err
	}
	sort.Strings(files)
	if len(ids) == 0 {
		return files, nil
	}
	want := map[string]bool{}
	for _, id := range ids {
		want[strings.TrimSpace(id)] = true
	}
	var out []string
	for _, f := range files {
		if want[strings.TrimSuffix(filepath.Base(f), ".csv")] {
			out = append(out, f)
		}
	}
	return out, nil
}

func Load(ctx context.Context, path string, cat categorize.Categorizer) (Company, error) {
	f, err := os.Open(path)
	if err != nil {
		return Company{}, err
	}
	defer f.Close()
	id := strings.TrimSuffix(filepath.Base(path), ".csv")
	b, err := casecsv.Parser{}.Parse(ctx, id, f)
	if err != nil {
		return Company{}, fmt.Errorf("%s: %w", path, err)
	}
	cleaned, quality := ingest.Deduplicate(b.Operations)
	b.Operations = cleaned
	res, err := cat.Categorize(ctx, b.Operations)
	if err != nil {
		return Company{}, err
	}
	categorize.Apply(b.Operations, res)
	return Company{ID: id, Ops: b.Operations, Quality: quality}, nil
}

// NotInternal — фильтр для потоков бизнеса: без своих переводов и займов
// учредителя.
func NotInternal(o domain.Operation) bool { return !o.Category.IsInternal() }

// FillBalance переносит последний известный остаток на дни без операций.
func FillBalance(flows []domain.DailyFlow) {
	var last *domain.Money
	for i := range flows {
		if flows[i].Balance != nil {
			last = flows[i].Balance
		} else if flows[i].Missing || flows[i].Inflow != 0 || flows[i].Outflow != 0 || hasCategoryMovement(flows[i]) {
			// Не выдавать перенесённый остаток за наблюдаемый факт в пропуске.
			last = nil
		} else if last != nil {
			b := *last
			flows[i].Balance = &b
		}
	}
}

func hasCategoryMovement(flow domain.DailyFlow) bool {
	for _, value := range flow.ByCategory {
		if value != 0 {
			return true
		}
	}
	return false
}
