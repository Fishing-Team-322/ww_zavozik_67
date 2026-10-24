package product

import "testing"

func TestOneCUndatedInvoiceDoesNotAppearOnDocumentDate(t *testing.T) {
	invoice := Doc{"source_kind": "onec_odata", "event_date": "2026-10-24", "due_date": nil, "status": "undated"}
	if calendarEventOnDate(invoice, "2026-10-24") {
		t.Fatal("document date was presented as a payment date")
	}
	invoice["due_date"] = "2026-11-20"
	invoice["event_date"] = "2026-11-20"
	if !calendarEventOnDate(invoice, "2026-11-20") {
		t.Fatal("dated invoice disappeared from calendar")
	}
	manual := Doc{"source_kind": "manual", "event_date": "2026-10-24"}
	if !calendarEventOnDate(manual, "2026-10-24") {
		t.Fatal("manual event disappeared from calendar")
	}
}
