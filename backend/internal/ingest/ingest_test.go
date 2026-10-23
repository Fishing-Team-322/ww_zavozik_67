package ingest

import (
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

func d(day int) time.Time { return time.Date(2025, 1, day, 0, 0, 0, 0, time.UTC) }

func TestDailyFlows(t *testing.T) {
	ops := []domain.Operation{
		{Date: d(1), Amount: 100, Direction: domain.In},
		{Date: d(1), Amount: 30, Direction: domain.Out},
		{Date: d(2), Amount: 5, Direction: domain.Out, Category: domain.CatOwnerLoan},
		{Date: d(20), Amount: 7, Direction: domain.In},
	}
	flows := DailyFlows(ops, d(1), d(21), func(o domain.Operation) bool { return !o.Category.IsInternal() })

	if len(flows) != 21 {
		t.Fatalf("want 21 days, got %d", len(flows))
	}
	if flows[0].Inflow != 100 || flows[0].Outflow != 30 {
		t.Errorf("day 1: %+v", flows[0])
	}
	if flows[1].Outflow != 0 {
		t.Errorf("internal op must be filtered: %+v", flows[1])
	}
	if flows[1].Missing || !flows[2].Missing || !flows[18].Missing || flows[19].Missing {
		t.Errorf("gap 3..19 must be missing")
	}
	if flows[20].Missing {
		t.Errorf("trailing quiet day is not a gap")
	}
}
