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
