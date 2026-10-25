package product

import (
	"strings"
	"testing"
	"time"
)

func TestTextParserRejectsPartialOrAmbiguousAmounts(t *testing.T) {
	for _, phrase := range []string{
		"заплачу 1000.001 руб 2026-11-20",
		"заплачу 1.234,56 руб 2026-11-20",
		"заплачу 100 руб и 200 руб 2026-11-20",
	} {
		if result, err := (&Service{}).parseEvent(Doc{"text": phrase}); err == nil {
			t.Errorf("accepted a partial/ambiguous monetary value in %q: %v", phrase, result.Body)
		}
	}
	got, err := (&Service{}).parseEvent(Doc{"text": "получим 1e6 руб 2026-11-20"})
	if err != nil {
		t.Fatal(err)
	}
	if got.Body.(Doc)["amount"] != float64(1000000) {
		t.Fatal("scientific amount was reduced to its suffix", got.Body)
	}
}

func TestTextParserSupportsDocumentedMoneyAndCharacterLimit(t *testing.T) {
	for _, tc := range []struct {
		phrase string
		amount float64
	}{
		{"клиент Альфа обещал 300 тысяч 20-го", 300000},
		{"куплю станок за 1 234,56 руб 2026-11-20", 1234.56},
		{"куплю станок за 1\u202f234,56 руб 2026-11-20", 1234.56},
		{"заплачу по счёту № 22 сумму 500 руб 2026-11-20", 500},
		{"получим 5к 2026-11-20", 5000},
	} {
		got, err := (&Service{}).parseEvent(Doc{"text": tc.phrase})
		if err != nil {
			t.Errorf("%s: %v", tc.phrase, err)
			continue
		}
		if got.Body.(Doc)["amount"] != tc.amount {
			t.Errorf("%s: %v", tc.phrase, got.Body)
		}
	}
	valid := "получим 100 руб 2026-11-20"
	parsed, err := (&Service{}).parseEvent(Doc{"text": strings.Repeat("🙂", 450) + valid})
	if err != nil {
		t.Fatal("valid 500-character text rejected by byte length", err)
	}
	draft := parsed.Body.(Doc)
	if err = validateResource("event", Doc{"date": draft["date"], "amount": draft["amount"], "direction": draft["direction"], "title": draft["title"]}, true); err != nil {
		t.Fatal("a valid parsed title cannot be saved because characters were counted as bytes", err)
	}
	if _, err := (&Service{}).parseEvent(Doc{"text": strings.Repeat("я", 500) + valid}); err == nil {
		t.Fatal("accepted more than the documented 500 characters")
	}
}

func TestTextParserDoesNotInventDirectionForMixedFlows(t *testing.T) {
	phrase := "заплачу поставщику 1000 руб, клиент заплатит позже 2026-11-20"
	if result, err := (&Service{}).parseEvent(Doc{"text": phrase}); err == nil {
		t.Fatal("mixed income/expense became one incoming payment", result.Body)
	}
}

func TestTextParserKeepsRequestedDayAcrossMonthRollover(t *testing.T) {
	for _, tc := range []struct{ now, phrase, want string }{
		{"2026-01-31", "заплачу 100 руб 30-го", "2026-03-30"},
		{"2026-04-24", "заплачу 100 руб 31-го", "2026-05-31"},
		{"2024-03-01", "заплачу 100 руб 29 февраля", "2028-02-29"},
		{"2026-10-25", "заплачу 100 руб 20 ноября 2027", "2027-11-20"},
	} {
		now, _ := time.Parse("2006-01-02", tc.now)
		got, err := parseEventAt(Doc{"text": tc.phrase}, now)
		if err != nil {
			t.Errorf("%s at %s: %v", tc.phrase, tc.now, err)
			continue
		}
		if got.Body.(Doc)["date"] != tc.want {
			t.Errorf("%s at %s: got %v want %s", tc.phrase, tc.now, got.Body.(Doc)["date"], tc.want)
		}
	}
}
