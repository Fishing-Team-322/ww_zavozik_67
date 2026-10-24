package taxcalendar

import (
	"errors"
	"fmt"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
)

// Deadline is a verified 2026 USN calendar date, not a calculated tax amount.
type Deadline struct {
	Regime        string `json:"regime"`
	PayerType     string `json:"payer_type"`
	Period        string `json:"period"`
	DueDate       string `json:"due_date"`
	AmountQuality string `json:"amount_quality"`
	SourceURL     string `json:"source_url"`
	VerifiedAt    string `json:"verified_at"`
}

func USN2026(payerType string) ([]Deadline, error) {
	if payerType != "legal_entity" && payerType != "sole_proprietor" {
		return nil, errors.New("payer_type must be legal_entity or sole_proprietor")
	}
	annual := "2026-03-30"
	annualURL := "https://www.nalog.gov.ru/rn72/news/tax_doc_news/16613450/"
	if payerType == "sole_proprietor" {
		annual = "2026-04-28"
		annualURL = "https://www.nalog.gov.ru/rn25/ifns/r25_02/info/16619330/"
	}
	rows := []struct{ period, due, url string }{
		{"2025_annual", annual, annualURL},
		{"2026_q1", "2026-04-28", "https://www.nalog.gov.ru/rn91/ifns/ifns_simph/info/16608587/"},
		{"2026_h1", "2026-07-28", "https://www.nalog.gov.ru/rn91/ifns/ifns_simph/info/16608587/"},
		{"2026_9m", "2026-10-28", "https://www.nalog.gov.ru/rn91/ifns/ifns_simph/info/16608587/"},
	}
	out := make([]Deadline, 0, len(rows))
	for _, row := range rows {
		out = append(out, Deadline{Regime: "USN", PayerType: payerType, Period: row.period, DueDate: row.due, AmountQuality: "unknown", SourceURL: row.url, VerifiedAt: "2026-10-24"})
	}
	return out, nil
}

// Confirm creates a cash-flow plan only after the business supplies a confirmed
// amount. A statutory deadline alone cannot imply a zero or estimated payment.
func Confirm(companyID string, deadline Deadline, amountKopecks int64, confirmedAt time.Time) (contracts.PlannedEvent, error) {
	if companyID == "" || deadline.Regime != "USN" || deadline.SourceURL == "" || amountKopecks <= 0 {
		return contracts.PlannedEvent{}, errors.New("confirmed tax plan requires company, verified deadline and positive amount")
	}
	if _, err := time.Parse("2006-01-02", deadline.DueDate); err != nil {
		return contracts.PlannedEvent{}, errors.New("invalid verified tax deadline")
	}
	due := deadline.DueDate
	return contracts.PlannedEvent{
		ExternalID: fmt.Sprintf("usn:%s:%s", deadline.PayerType, deadline.Period), Date: due,
		AmountKopecks: amountKopecks, Direction: "out", Title: "Подтверждённый платёж УСН",
		SourceKind: "tax_calendar", Status: "expected", DueDate: &due, DateQuality: "statutory_verified",
		TotalKopecks: amountKopecks, RemainingKopecks: amountKopecks, Currency: "RUB",
		LinkStatus: "manual_confirmed", ForecastEligible: true, RawReference: deadline.SourceURL,
		DataMode: "manual", ObservedAt: confirmedAt.UTC().Format(time.RFC3339),
	}, nil
}

