package product

import (
	"testing"
	"time"
)

func TestMoneyAndMalformedSchedules(t *testing.T) {
	for _, s := range []string{"NaN", "Inf", "0.001", "10000000000001"} {
		if _, e := parseAmount(s); e == nil {
			t.Fatalf("accepted %s", s)
		}
	}
	if n, e := parseAmount("1 234,56"); e != nil || n != 1234.56 {
		t.Fatalf("%v %v", n, e)
	}
	for _, kind := range []string{"scenario", "contract"} {
		key := "steps"
		if kind == "contract" {
			key = "schedule"
		}
		if e := validateResource(kind, Doc{key: []any{map[string]any{}, "invalid"}}, false); e == nil {
			t.Fatal("accepted malformed", kind)
		}
	}
}

func TestProductionCalendarAndMonthEnd(t *testing.T) {
	if isWorkday(time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)) {
		t.Fatal("New Year must be a holiday")
	}
	if !isWorkday(time.Date(2026, 10, 26, 0, 0, 0, 0, time.UTC)) {
		t.Fatal("ordinary Monday must be a workday")
	}
	after := time.Date(2026, 1, 31, 0, 0, 0, 0, time.UTC)
	if got := nextOccurrence(after, "monthly", 31).Format("2006-01-02"); got != "2026-02-28" {
		t.Fatal(got)
	}
}
