package product

import (
	"testing"
	"time"
)

func TestForecastPaymentDatesPreserveDebtsWithoutInventingReceipts(t *testing.T) {
	asOf := time.Date(2026, 10, 23, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name, status, direction, date string
		additional, include           bool
		want                          string
	}{
		{"unpaid debt", "missed", "out", "2026-10-20", true, true, "2026-10-24"},
		{"worker not run yet", "expected", "out", "2026-10-23", true, true, "2026-10-24"},
		{"paid debt", "received", "out", "2026-10-20", true, false, ""},
		{"cancelled debt", "cancelled", "out", "2026-10-20", true, false, ""},
		{"missed income", "missed", "in", "2026-10-20", true, false, ""},
		{"past income", "expected", "in", "2026-10-20", true, false, ""},
		{"ordinary expense", "missed", "out", "2026-10-20", false, false, ""},
		{"future receipt", "expected", "in", "2026-10-25", true, true, "2026-10-25"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			event := Doc{"event_date": tc.date, "direction": tc.direction, "status": tc.status, "additional": tc.additional}
			got, include := eventForecastDate(event, asOf)
			if include != tc.include || include && got.Format(time.DateOnly) != tc.want {
				t.Fatalf("date=%s include=%v", got, include)
			}
			if event["event_date"] != tc.date {
				t.Fatal("calendar history changed")
			}
		})
	}
}

func TestPaymentCounterpartyIdentity(t *testing.T) {
	for _, tc := range []struct {
		name             string
		event, operation Doc
		want             bool
	}{
		{"different INNs", Doc{"counterparty_inn": "7707083893", "counterparty_name": "Same"}, Doc{"counterparty_inn": "7736050003", "counterparty_name": "Same"}, false},
		{"same INN after rename", Doc{"counterparty_inn": "7707083893", "counterparty_name": "Old"}, Doc{"counterparty_inn": "7707083893", "counterparty_name": "New"}, true},
		{"legacy name only", Doc{"counterparty_name": "Same"}, Doc{"counterparty_inn": "7736050003", "counterparty_name": "Same"}, true},
		{"no identity", Doc{}, Doc{}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := samePaymentCounterparty(tc.event, tc.operation); got != tc.want {
				t.Fatalf("got %v", got)
			}
		})
	}
}
