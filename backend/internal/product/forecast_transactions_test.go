package product

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"testing"
	"time"
)

func TestM6TransactionsExcludeReconciliationGapsAndNormalizeUnknown(t *testing.T) {
	start := time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)
	rows := []domain.Operation{
		{ID: "observed", Date: start, Amount: 10, Direction: domain.In, Purpose: "Исходное назначение №15 от01.10.2026"},
		{ID: "missing", Date: start.AddDate(0, 0, 1), Amount: 20, Direction: domain.Out, Category: domain.CatSalary},
		{ID: "future", Date: start.AddDate(0, 0, 2), Amount: 30, Direction: domain.In, Category: domain.CatRevenueB2B},
		{ID: "internal", Date: start, Amount: 40, Direction: domain.In, Category: domain.CatOwnerLoan},
	}
	flows := []domain.DailyFlow{{Date: start}, {Date: start.AddDate(0, 0, 1), Missing: true}}
	got := observedTransactions("company", rows, flows)
	if len(got) != 2 || got[0].ID != "observed" || got[1].ID != "internal" {
		t.Fatalf("invalid observation scope: %+v", got)
	}
	if got[0].Category != domain.CatOther || got[0].Purpose != rows[0].Purpose {
		t.Fatal("unknown category/raw purpose contract lost")
	}
	if got[1].Category != domain.CatOwnerLoan {
		t.Fatal("internal category lost; M6 must receive its scope marker")
	}
}
