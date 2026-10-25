package product

import (
	"testing"
	"time"
)

func TestSavedForecastRiskChecksEachSnapshotAtReadTime(t *testing.T) {
	now := time.Date(2026, 10, 25, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name  string
		extra Doc
	}{
		{"low confidence overrides saved true", Doc{"low_confidence": true}},
		{"fallback overrides saved true", Doc{"fallback_used": true}},
		{"missing history overrides saved true", Doc{"warnings": []any{"incomplete_history"}}},
		{"statement aged since saving", Doc{"as_of": "2026-09-29"}},
		{"future statement", Doc{"as_of": "2026-10-26"}},
		{"missing date", Doc{"as_of": ""}},
		{"explicitly unreliable", Doc{"probability_reliable": false}},
		{"gap independently unreliable", Doc{"gaps": []Doc{{"date": "2026-11-01", "probability": .7, "probability_reliable": false}}}},
		{"empty alerts cannot establish zero risk", Doc{"gaps": []Doc{}}},
		{"invalid probability", Doc{"gaps": []Doc{{"date": "2026-11-01", "probability": 1.2}}}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			snapshot := Doc{"as_of": "2026-10-24", "probability_reliable": true, "gaps": []Doc{{"date": "2026-11-01", "probability": .7}}}
			for key, value := range tc.extra {
				snapshot[key] = value
			}
			probability, _, reliable := savedForecastRisk(snapshot, now)
			if probability != nil || reliable {
				t.Fatal("unreliable snapshot leaked a numeric probability", probability, reliable)
			}
		})
	}
	for _, explicit := range []bool{false, true} {
		snapshot := Doc{"as_of": "2026-10-24", "gaps": []Doc{{"date": "2026-11-01", "probability": .7}}}
		if explicit {
			snapshot["probability_reliable"] = true
		}
		probability, date, reliable := savedForecastRisk(snapshot, now)
		if probability != .7 || date != "2026-11-01" || !reliable {
			t.Fatal("reliable forecast estimate lost", probability, date, reliable)
		}
	}
}
