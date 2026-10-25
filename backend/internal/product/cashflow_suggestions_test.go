package product

import (
	"context"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func TestCashflowSuggestionEffectsUseWholeHorizon(t *testing.T) {
	base, events := scenarioFixture(t, "out", true, "supplier")
	base.OpeningBalance = 500
	if err := base.Recompute(); err != nil {
		t.Fatal(err)
	}
	gap := Doc{"date": "2026-10-24", "shortfall": float64(500), "shortfall_p90": float64(500)}
	actions := cashflowCandidates("tenant", "snapshot", gap, base, events)
	shift := actions[0]
	changed, err := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, docs(shift["steps"]))
	if err != nil {
		t.Fatal(err)
	}
	effect := cashflowEffect(base, changed, 0, false)
	if number(effect, "baseline_shortfall") != 500 || number(effect, "new_shortfall") != 0 || number(effect, "shortfall_reduction") != 500 || !flag(shift, "deferred_beyond_horizon") || flag(effect, "probability_reliable") {
		t.Fatal(shift, effect)
	}
	// A deferral inside the horizon only changes timing, not the worst deficit.
	changed, err = (&Service{}).applySteps(context.Background(), "", "tenant", base, events, []Doc{{"kind": "move_event", "event_id": "fixture", "date": "2026-10-26"}})
	if err != nil {
		t.Fatal(err)
	}
	effect = cashflowEffect(base, changed, 0, true)
	if number(effect, "shortfall_reduction") != 0 || flag(effect, "closes_gap") || effect["new_gap_date"] != "2026-10-26" {
		t.Fatal(effect)
	}
}

func TestCashflowCandidatesExcludeProtectedAndPaidPlans(t *testing.T) {
	base, events := scenarioFixture(t, "out", true, "tax")
	gap := Doc{"date": "2026-10-24", "shortfall_p90": float64(500)}
	for _, category := range []string{"tax", "salary", "loan_payment", "leasing", "enforcement"} {
		events[0]["category"] = category
		if actions := cashflowCandidates("tenant", "snapshot", gap, base, events); len(actions) != 1 || text(actions[0], "kind") != "overdraft" {
			t.Fatal(category, actions)
		}
	}
	events[0]["category"], events[0]["status"] = "supplier", "received"
	if actions := cashflowCandidates("tenant", "snapshot", gap, base, events); len(actions) != 1 {
		t.Fatal(actions)
	}
}

func TestCashflowReceiptAccelerationKeepsProbabilityAndBankFacts(t *testing.T) {
	base, events := scenarioFixture(t, "in", true, "revenue_b2b")
	events[0]["event_date"] = "2026-10-28"
	base.Deterministic[0].Date = base.Dates[4]
	base.OpeningBalance = -500
	if err := base.Recompute(); err != nil {
		t.Fatal(err)
	}
	actions := cashflowCandidates("tenant", "snapshot", Doc{"date": "2026-10-24", "shortfall_p90": float64(500)}, base, events)
	if text(actions[0], "kind") != "accelerate_receivable" {
		t.Fatal(actions)
	}
	changed, err := (&Service{}).applySteps(context.Background(), "", "tenant", base, events, docs(actions[0]["steps"]))
	if err != nil {
		t.Fatal(err)
	}
	effect := cashflowEffect(base, changed, 0, true)
	if number(effect, "shortfall_reduction") != 500 || !flag(effect, "closes_gap") {
		t.Fatal(effect)
	}
	if events[0]["event_date"] != "2026-10-28" || base.Balances[0][0] != -500 {
		t.Fatal("suggestion mutated baseline")
	}
	// An early receipt with low probability must not become guaranteed income.
	base.Deterministic = nil
	base.Uncertain = []forecast.PathComponent{{Date: base.Dates[4], Key: "event:fixture", Values: []float64{0}}}
	events[0]["probability"] = float64(0)
	if err := base.Recompute(); err != nil {
		t.Fatal(err)
	}
	changed, err = (&Service{}).applySteps(context.Background(), "", "tenant", base, events, docs(actions[0]["steps"]))
	if err != nil {
		t.Fatal(err)
	}
	if flag(cashflowEffect(base, changed, 0, false), "closes_gap") {
		t.Fatal("uncertain receipt treated as guaranteed")
	}
}
