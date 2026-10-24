package taxcalendar

import (
	"testing"
	"time"
)

func TestUSN2026(t *testing.T) {
	legal, err := USN2026("legal_entity")
	if err != nil || len(legal) != 4 || legal[0].DueDate != "2026-03-30" || legal[1].DueDate != "2026-04-28" || legal[3].DueDate != "2026-10-28" {
		t.Fatalf("legal: %+v %v", legal, err)
	}
	ip, err := USN2026("sole_proprietor")
	if err != nil || ip[0].DueDate != "2026-04-28" {
		t.Fatalf("IP: %+v %v", ip, err)
	}
	if _, err := USN2026("unknown"); err == nil {
		t.Fatal("unknown payer accepted")
	}
	plan, err := Confirm("demo-company", legal[1], 14000000, time.Date(2026, 10, 24, 0, 0, 0, 0, time.UTC))
	if err != nil || plan.Direction != "out" || plan.AmountKopecks != 14000000 || !plan.ForecastEligible {
		t.Fatalf("plan: %+v %v", plan, err)
	}
	if _, err := Confirm("demo-company", legal[1], 0, time.Now()); err == nil {
		t.Fatal("unknown amount converted to zero plan")
	}
}
