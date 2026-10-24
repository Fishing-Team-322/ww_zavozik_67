package product

import (
	"context"
	"math"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func scenarioFixture(t *testing.T, direction string, additional bool, category string) (forecast.Result, []Doc) {
	t.Helper()
	as := time.Date(2026, 10, 23, 0, 0, 0, 0, time.UTC)
	event := Doc{"id": "fixture", "event_date": "2026-10-24", "title": "Fixture", "direction": direction, "amount": float64(1000), "probability": float64(1), "status": "expected", "additional": additional, "category": category, "source_kind": "recurring", "counterparty_name": "Client"}
	sf := forecast.StochasticForecast{Inflow: [][]float64{make([]float64, 10)}, Outflow: [][]float64{make([]float64, 10)}}
	r := forecast.Result{AsOf: as, OpeningBalance: 10000, Stochastic: sf}
	for i := 0; i < 10; i++ {
		r.Dates = append(r.Dates, as.AddDate(0, 0, i+1))
	}
	if additional {
		amount := domain.Money(1000)
		if direction == "out" {
			amount = -amount
		}
		r.Deterministic = []forecast.ComponentFlow{{Date: r.Dates[0], Key: "event:fixture", Amount: amount}}
	} else if direction == "in" {
		r.Stochastic.Inflow[0][0] = 1000
	} else {
		r.Stochastic.Outflow[0][0] = 1000
	}
	if e := r.Recompute(); e != nil {
		t.Fatal(e)
	}
	return r, []Doc{event}
}
func TestScenarioRepeatedMoveDoesNotDuplicateOffsets(t *testing.T) {
	base, events := scenarioFixture(t, "in", false, "revenue_b2b")
	got, e := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "move_event", "event_id": "fixture", "date": "2026-10-25"}, {"kind": "move_event", "event_id": "fixture", "date": "2026-10-26"}})
	if e != nil {
		t.Fatal(e)
	}
	for i, want := range []float64{10000, 10000, 11000} {
		if math.Abs(got.Balances[0][i]-want) > .01 {
			t.Errorf("day %d: got %.2f, want %.2f", i, got.Balances[0][i], want)
		}
	}
}
func TestScenarioRevenueScalingDoesNotScaleAnExpenseReversal(t *testing.T) {
	base, events := scenarioFixture(t, "out", false, "rent")
	got, e := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "move_event", "event_id": "fixture", "date": "2026-10-26"}, {"kind": "scale_revenue", "factor": 0.5}})
	if e != nil {
		t.Fatal(e)
	}
	if got.Balances[0][0] != 10000 {
		t.Fatalf("revenue reduction changed an expense compensation: %.2f", got.Balances[0][0])
	}
}
func TestScenarioRevenueScalingPreservesOwnerFinancing(t *testing.T) {
	base, events := scenarioFixture(t, "in", true, "owner_loan")
	got, e := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "scale_revenue", "factor": float64(0)}})
	if e != nil {
		t.Fatal(e)
	}
	if got.Balances[0][0] != 11000 {
		t.Fatalf("owner financing was removed with revenue: %.2f", got.Balances[0][0])
	}
}
func TestScenarioSequentialDelaysUseCurrentDate(t *testing.T) {
	base, events := scenarioFixture(t, "in", true, "revenue_b2b")
	got, e := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "delay_counterparty", "counterparty_name": "Client", "delay_days": float64(2)}, {"kind": "delay_counterparty", "counterparty_name": "Client", "delay_days": float64(3)}})
	if e != nil {
		t.Fatal(e)
	}
	if got.Balances[0][3] != 10000 || got.Balances[0][5] != 11000 {
		t.Fatalf("two delays did not compose: %v", got.Balances[0])
	}
	if events[0]["event_date"] != "2026-10-24" {
		t.Fatal("scenario mutated its input events")
	}
}
func TestScenarioSequentialFixedCostScalingCompounds(t *testing.T) {
	for _, additional := range []bool{false, true} {
		t.Run(map[bool]string{true: "additional", false: "baseline"}[additional], func(t *testing.T) {
			base, events := scenarioFixture(t, "out", additional, "rent")
			got, e := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "scale_fixed_costs", "factor": 1.1}, {"kind": "scale_fixed_costs", "factor": 1.1}})
			if e != nil {
				t.Fatal(e)
			}
			if math.Abs(got.Balances[0][0]-8790) > .01 {
				t.Fatalf("cost should be 1000*1.1*1.1=1210, got balance %.2f", got.Balances[0][0])
			}
		})
	}
}
func TestScenarioRejectsExpenseInsideObservedHistory(t *testing.T) {
	base, events := scenarioFixture(t, "out", false, "rent")
	_, e := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "add_expense", "amount": float64(1000), "date": "2026-10-22"}})
	if e == nil {
		t.Fatal("expense in observed history was silently ignored")
	}
}

func TestScenarioRevenueAndMoveComposeInEitherOrder(t *testing.T) {
	for _, additional := range []bool{false, true} {
		base, events := scenarioFixture(t, "in", additional, "revenue_b2b")
		move := Doc{"kind": "move_event", "event_id": "fixture", "date": "2026-10-26"}
		scale := Doc{"kind": "scale_revenue", "factor": 0.5}
		for _, steps := range [][]Doc{{move, scale}, {scale, move}} {
			got, e := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, steps)
			if e != nil {
				t.Fatal(e)
			}
			if math.Abs(got.Balances[0][0]-10000) > .01 || math.Abs(got.Balances[0][2]-10500) > .01 {
				t.Fatalf("move/revenue composition failed (additional=%v): %v", additional, got.Balances[0])
			}
		}
	}
}
func TestScenarioFixedCostsAndMoveComposeInEitherOrder(t *testing.T) {
	for _, additional := range []bool{false, true} {
		base, events := scenarioFixture(t, "out", additional, "rent")
		move := Doc{"kind": "move_event", "event_id": "fixture", "date": "2026-10-26"}
		scale := Doc{"kind": "scale_fixed_costs", "factor": 1.1}
		for _, steps := range [][]Doc{{move, scale, scale}, {scale, move, scale}, {scale, scale, move}} {
			got, e := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, steps)
			if e != nil {
				t.Fatal(e)
			}
			if math.Abs(got.Balances[0][0]-10000) > .01 || math.Abs(got.Balances[0][2]-8790) > .01 {
				t.Fatalf("move/cost composition failed (additional=%v): %v", additional, got.Balances[0])
			}
		}
	}
}
func TestScenarioDelaySkipsHistoricalUnconfirmedReceipts(t *testing.T) {
	base, events := scenarioFixture(t, "in", true, "revenue_b2b")
	events = append(events, Doc{"id": "past", "event_date": "2026-10-20", "direction": "in", "status": "expected", "amount": float64(1000), "counterparty_name": "Client"})
	_, e := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "delay_counterparty", "counterparty_name": "Client", "delay_days": float64(2)}})
	if e != nil {
		t.Fatalf("an old unmatched receipt blocked the future scenario: %v", e)
	}
}

func TestScenarioCounterpartyIDTakesPrecedenceOverDisplayName(t *testing.T) {
	base, events := scenarioFixture(t, "in", true, "revenue_b2b")
	events[0]["counterparty_inn"] = "7707083893"
	events = append(events, Doc{"id": "other", "event_date": "2026-10-24", "title": "Other client", "direction": "in", "amount": float64(2000), "probability": float64(1), "status": "expected", "additional": true, "counterparty_name": "Client", "counterparty_inn": "7736207543"})
	base.Deterministic = append(base.Deterministic, forecast.ComponentFlow{Date: base.Dates[0], Key: "event:other", Amount: 2000})
	if err := base.Recompute(); err != nil {
		t.Fatal(err)
	}
	selected := cpRef("tenant", events[0])["id"]
	got, err := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "delay_counterparty", "counterparty_id": selected, "counterparty_name": "Client", "delay_days": float64(2)}})
	if err != nil {
		t.Fatal(err)
	}
	if got.Balances[0][0] != 12000 || got.Balances[0][2] != 13000 {
		t.Fatal("a selected client's display name delayed another legal entity", got.Balances[0])
	}
}

func TestMovingAnAdditionalPlanIntoHorizonPreservesItsProbability(t *testing.T) {
	for _, prob := range []float64{0, 0.5, 1} {
		base, events := scenarioFixture(t, "in", true, "revenue_b2b")
		events[0]["event_date"], events[0]["probability"] = "2026-12-01", prob
		base.Deterministic = nil // Original plan is outside the visible horizon.
		// Multiple paths expose the distinction between an uncertain and certain receipt.
		base.Stochastic.Inflow, base.Stochastic.Outflow = nil, nil
		for i := 0; i < 600; i++ {
			base.Stochastic.Inflow = append(base.Stochastic.Inflow, make([]float64, 10))
			base.Stochastic.Outflow = append(base.Stochastic.Outflow, make([]float64, 10))
		}
		if err := base.Recompute(); err != nil {
			t.Fatal(err)
		}
		got, err := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "move_event", "event_id": "fixture", "date": "2026-10-26"}})
		if err != nil {
			t.Fatal(err)
		}
		received := 0
		for _, path := range got.Balances {
			if path[2] == 11000 {
				received++
			} else if path[2] != 10000 {
				t.Fatal("receipt is neither absent nor fully paid", path[2])
			}
		}
		if (prob == 0 && received != 0) || (prob == 1 && received != 600) || (prob == 0.5 && (received < 200 || received > 400)) {
			t.Errorf("moving a plan changed probability %v into %d/600 certain receipts", prob, received)
		}
	}
}
