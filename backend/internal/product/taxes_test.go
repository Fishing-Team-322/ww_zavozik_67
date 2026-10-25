package product

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"testing"
)

func TestTaxCalendarAndKopecks(t *testing.T) {
	for _, tc := range []struct {
		kind, period, legal string
		year                int
		want                []string
	}{
		{"usn_annual", "year", "ООО", 2026, []string{"2027-03-29"}},
		{"usn_annual", "year", "ИП", 2026, []string{"2027-04-28"}},
		{"usn_advance", "9m", "ООО", 2026, []string{"2026-10-28"}},
		{"vat", "q1", "ООО", 2026, []string{"2026-04-28", "2026-05-28", "2026-06-29"}},
		{"enp", "m11", "ООО", 2026, []string{"2026-11-30"}},
		{"contributions", "m10", "ООО", 2026, []string{"2026-11-30"}},
		{"contributions", "m12", "ИП", 2026, []string{"2027-01-28"}},
	} {
		dates, _, err := taxDates(tc.kind, tc.period, tc.legal, "", tc.year)
		if err != nil {
			t.Fatal(err)
		}
		if len(dates) != len(tc.want) {
			t.Fatal(dates)
		}
		for i, d := range dates {
			if d.Format("2006-01-02") != tc.want[i] {
				t.Fatalf("%s %s: %v", tc.kind, tc.legal, dates)
			}
		}
	}
	b := Doc{"kind": "vat", "period": "q1", "year": float64(2026), "amount": 100.01, "title": "НДС", "source_ref": "Декларация", "confirmed": true, "additional": true}
	d, e := taxDraft(platform.Company{LegalForm: "ООО"}, b, true)
	if e != nil {
		t.Fatal(e)
	}
	payments := docs(d["payments"])
	sum := 0.0
	for _, p := range payments {
		sum += number(p, "amount")
	}
	if money(sum) != 100.01 || number(payments[0], "amount") != 33.34 || number(payments[2], "amount") != 33.33 {
		t.Fatal(payments)
	}
	if _, _, e := taxDates("vat", "q4", "ООО", "", 2099); e == nil {
		t.Fatal("invented an unsupported production calendar")
	}
	if _, _, e := taxDates("usn_advance", "q2", "ООО", "", 2026); e == nil {
		t.Fatal("invalid USN cumulative period accepted")
	}
	b["confirmed"] = false
	if _, e := taxDraft(platform.Company{}, b, true); e == nil {
		t.Fatal("unconfirmed tax accepted")
	}
}
