package product

import (
	"testing"
	"time"
)

func TestForecastRecommendationRequiresCurrentVerifiedData(t *testing.T) {
	now := time.Date(2026, 10, 25, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name, asOf    string
		fallback, low bool
		unconfirmed   int
		available     bool
	}{
		{"current", "2026-10-24", false, false, 0, true},
		{"stale", "2026-09-29", false, false, 0, false},
		{"future", "2026-10-26", false, false, 0, false},
		{"fallback", "2026-10-24", true, false, 0, false},
		{"limited", "2026-10-24", false, true, 0, false},
		{"unverified plans", "2026-10-24", false, false, 5, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			out := Doc{"as_of": tc.asOf, "status": "ok", "safe_to_spend": 1000.0, "fallback_used": tc.fallback, "low_confidence": tc.low, "points": []Doc{{"date": "2026-11-23"}}, "gaps": []Doc{{"date": "2026-11-01", "probability": 0.7}}}
			annotateForecast(out, now, tc.unconfirmed)
			if flag(out, "spending_available") != tc.available {
				t.Fatal(out)
			}
			if !tc.available && out["safe_to_spend"] != 0.0 {
				t.Fatal(out)
			}
			if docs(out["gaps"])[0]["days_left"] != 7 {
				t.Fatal(out)
			}
			if (tc.fallback || tc.low || tc.name == "stale" || tc.name == "future") && flag(out, "probability_reliable") {
				t.Fatal(out)
			}
		})
	}
}

func TestCaseDatasetHeadersAreRecognizedWithoutManualMapping(t *testing.T) {
	m := proposeMapping([]string{"operation_date", "amount", "direction", "counterparty_name", "counterparty_inn", "payment_purpose", "balance_eod", "operation_id"})
	if !mappingReady(m) || text(m, "purpose") != "payment_purpose" || text(m, "id") != "operation_id" {
		t.Fatal(m)
	}
}

func TestIncompleteHistoryOverridesOtherwiseReliableForecast(t *testing.T) {
	now := time.Date(2026, 10, 25, 0, 0, 0, 0, time.UTC)
	for _, warnings := range []any{
		[]string{"lite_mode_no_purposes", "incomplete_history"},
		[]any{"lite_mode_no_purposes", "incomplete_history"},
	} {
		out := Doc{"as_of": "2026-10-24", "status": "ok", "safe_to_spend": 1000.0,
			"fallback_used": false, "low_confidence": false, "probability_reliable": true,
			"spending_available": true, "warnings": warnings,
			"gaps": []Doc{{"date": "2026-11-01", "probability": 0.7}}}
		annotateForecast(out, now, 0)
		if flag(out, "spending_available") || flag(out, "probability_reliable") || number(out, "safe_to_spend") != 0 {
			t.Fatal("incomplete history advertised reliable spending or probability", out)
		}
		if text(out, "status") != "warning" || flag(docs(out["gaps"])[0], "probability_reliable") {
			t.Fatal("restriction did not reach forecast and gap presentation", out)
		}
		restrictions := stringsList(out["spending_restrictions"])
		found := false
		for _, reason := range restrictions {
			found = found || reason == "incomplete_history"
		}
		if !found {
			t.Fatal("missing restriction reason", out)
		}
	}
}

func TestWarningOnlySnapshotsDoNotExposeIncompleteHistoryProbability(t *testing.T) {
	for _, warnings := range []any{[]string{"incomplete_history"}, []any{"incomplete_history"}} {
		for _, explicitFlag := range []bool{false, true} {
			out := Doc{"warnings": warnings, "fallback_used": false, "low_confidence": false}
			if explicitFlag {
				out["probability_reliable"] = true
			}
			if reliableProbability(out) || cashflowProbabilityReliable(out) {
				t.Fatal("legacy warning-only snapshot advertised reliable probability", out)
			}
		}
	}
}

func TestLiteModeWarningAloneDoesNotRestrictForecast(t *testing.T) {
	out := Doc{"as_of": "2026-10-24", "status": "ok", "safe_to_spend": 1000.0,
		"fallback_used": false, "low_confidence": false, "warnings": []string{"lite_mode_no_purposes"}}
	annotateForecast(out, time.Date(2026, 10, 25, 0, 0, 0, 0, time.UTC), 0)
	if !flag(out, "spending_available") || !flag(out, "probability_reliable") || number(out, "safe_to_spend") != 1000 || !reliableProbability(out) || !cashflowProbabilityReliable(out) {
		t.Fatal("informational lite-mode warning blocked the forecast", out)
	}
}
