package demo

import "sort"

type Event struct {
	ExternalID    string `json:"external_id"`
	Date          string `json:"date"`
	Kind          string `json:"kind"`
	Direction     string `json:"direction"`
	AmountKopecks int64  `json:"amount_kopecks"`
	Source        string `json:"source"`
	DataMode      string `json:"data_mode"`
	Status        string `json:"status"`
	Version       int64  `json:"version"`
}
type Day struct {
	Date           string `json:"date"`
	BalanceKopecks int64  `json:"balance_kopecks"`
}
type Scenario struct {
	OpeningKopecks int64   `json:"opening_kopecks"`
	Events         []Event `json:"events"`
	Balances       []Day   `json:"balances"`
	ClosingKopecks int64   `json:"closing_kopecks"`
}
type Comparison struct {
	Before Scenario `json:"before"`
	After  Scenario `json:"after"`
}

func Build() Comparison {
	before := []Event{
		{"invoice-client", "2026-11-05", "planned", "in", 35000000, "onec_odata", "fixture", "expected", 1},
		{"invoice-supplier", "2026-11-06", "planned", "out", 18000000, "onec_odata", "fixture", "expected", 1},
		{"usn-confirmed", "2026-11-09", "planned", "out", 14000000, "tax_calendar", "fixture", "expected", 1},
	}
	after := []Event{
		{"payment-client-1", "2026-11-05", "actual", "in", 10000000, "onec_odata", "fixture", "posted", 1},
		{"invoice-supplier", "2026-11-06", "planned", "out", 18000000, "onec_odata", "fixture", "expected", 1},
		{"usn-confirmed", "2026-11-09", "planned", "out", 14000000, "tax_calendar", "fixture", "expected", 1},
		{"invoice-client", "2026-11-19", "planned", "in", 25000000, "onec_odata", "fixture", "partially_paid", 2},
	}
	return Comparison{Before: calculate(before), After: calculate(after)}
}

func calculate(events []Event) Scenario {
	sort.Slice(events, func(i, j int) bool { return events[i].Date < events[j].Date })
	balance := int64(22000000)
	balances := make([]Day, 0, len(events))
	for _, event := range events {
		if event.Direction == "in" {
			balance += event.AmountKopecks
		} else {
			balance -= event.AmountKopecks
		}
		balances = append(balances, Day{event.Date, balance})
	}
	return Scenario{OpeningKopecks: 22000000, Events: events, Balances: balances, ClosingKopecks: balance}
}
