package ingest

import (
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

func d(day int) time.Time           { return time.Date(2025, 1, day, 0, 0, 0, 0, time.UTC) }
func money(v float64) *domain.Money { m := domain.Money(v); return &m }

func TestDailyFlowsQuietIsNotMissing(t *testing.T) {
	ops := []domain.Operation{
		{Date: d(1), Amount: 100, Direction: domain.In, BalanceEOD: money(200)},
		{Date: d(20), Amount: 50, Direction: domain.Out, BalanceEOD: money(150)},
	}
	flows, known := DailyFlowsWithDetection(ops, d(1), d(21), nil)
	for i, f := range flows {
		if f.Missing || !known[i].IsZero() {
			t.Fatalf("quiet day %d treated as data loss", i+1)
		}
	}
	if flows[0].Inflow != 100 || flows[19].Outflow != 50 {
		t.Fatal("incorrect flows")
	}
}

func TestBalanceJumpFlagsIntervalWhenObserved(t *testing.T) {
	ops := []domain.Operation{
		{Date: d(1), Amount: 100, Direction: domain.In, BalanceEOD: money(200)},
		{Date: d(5), Amount: 50, Direction: domain.Out, BalanceEOD: money(100)},
	}
	flows, known := DailyFlowsWithDetection(ops, d(1), d(6), nil)
	for i := 1; i <= 4; i++ {
		if !flows[i].Missing || !known[i].Equal(d(5)) {
			t.Fatalf("day %d must be flagged on Jan 5", i+1)
		}
	}
	if flows[0].Missing || flows[5].Missing {
		t.Fatal("outside incomplete interval")
	}
	prefix := DailyFlows(ops[:1], d(1), d(4), nil)
	for _, f := range prefix {
		if f.Missing {
			t.Fatal("future observation leaked into historical preparation")
		}
	}
}

func TestInternalTransfersStillReconcile(t *testing.T) {
	ops := []domain.Operation{
		{Date: d(1), Amount: 100, Direction: domain.In, BalanceEOD: money(200)},
		{Date: d(2), Amount: 50, Direction: domain.In, Category: domain.CatOwnerLoan, BalanceEOD: money(250)},
	}
	f := DailyFlows(ops, d(1), d(2), func(o domain.Operation) bool { return !o.Category.IsInternal() })
	if f[1].Missing || f[1].Inflow != 0 || f[1].ByCategory[domain.CatOwnerLoan] != 50 {
		t.Fatal("filter must not affect balance reconciliation")
	}
}

func TestNoBalanceDoesNotInventMissingDays(t *testing.T) {
	ops := []domain.Operation{{Date: d(1), Amount: 1, Direction: domain.In}, {Date: d(25), Amount: 2, Direction: domain.In}}
	for _, f := range DailyFlows(ops, d(1), d(31), nil) {
		if f.Missing {
			t.Fatal("cannot prove missing from silence alone")
		}
	}
}

func TestDedupRequiresBalanceEvidence(t *testing.T) {
	first := domain.Operation{ID: "1", CompanyID: "C", Date: d(1), Amount: 100, Direction: domain.In, BalanceEOD: money(200)}
	a := domain.Operation{ID: "2", CompanyID: "C", Date: d(2), Amount: 30, Direction: domain.Out, BalanceEOD: money(170)}
	b := a
	b.ID = "3"
	clean, r := Deduplicate([]domain.Operation{first, a, b})
	if len(clean) != 2 || r.Removed != 1 {
		t.Fatalf("confirmed duplicate retained: %+v", r)
	}
	a.BalanceEOD = money(140)
	b.BalanceEOD = money(140)
	clean, r = Deduplicate([]domain.Operation{first, a, b})
	if len(clean) != 3 || r.Removed != 0 {
		t.Fatal("legitimate equal payments deleted")
	}
	clean, r = Deduplicate([]domain.Operation{a, b})
	if len(clean) != 2 || r.Removed != 0 || r.Unconfirmed != 1 {
		t.Fatal("first-day duplicate is not identifiable")
	}
}

func TestDedupKeepsUnexplainedMismatch(t *testing.T) {
	a := domain.Operation{Date: d(1), Amount: 100, Direction: domain.In, BalanceEOD: money(100)}
	b := domain.Operation{Date: d(2), Amount: 20, Direction: domain.Out, BalanceEOD: money(50)}
	clean, r := Deduplicate([]domain.Operation{a, b, b})
	if len(clean) != 3 || r.Removed != 0 {
		t.Fatal("deleting duplicate does not reconcile this mismatch")
	}
}
