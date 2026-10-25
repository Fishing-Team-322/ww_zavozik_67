package product

import (
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// Reliability describes the product recommendation, without changing model paths.
// Keep the numerical forecast available for inspection, but never advertise an
// actionable spending allowance when its inputs have not been verified.
func annotateForecast(out Doc, now time.Time, unconfirmed int) {
	asOf, err := day(text(out, "as_of"))
	if err != nil {
		return
	}
	current, _ := day(now.Format(domain.DateLayout))
	age := int(current.Sub(asOf).Hours() / 24)
	reasons := []string{}
	if age > 7 {
		reasons = append(reasons, "stale_statement")
	} else if age < 0 {
		reasons = append(reasons, "future_statement")
	}
	if flag(out, "fallback_used") || flag(out, "low_confidence") {
		reasons = append(reasons, "limited_forecast")
	}
	incomplete := hasIncompleteHistory(out)
	if incomplete {
		reasons = append(reasons, "incomplete_history")
	}
	if unconfirmed > 0 {
		reasons = append(reasons, "unconfirmed_recurring")
	}
	out["data_age_days"] = age
	out["unconfirmed_recurring"] = unconfirmed
	out["spending_available"] = len(reasons) == 0
	out["spending_restrictions"] = reasons
	out["probability_reliable"] = age >= 0 && age <= 7 && !flag(out, "fallback_used") && !flag(out, "low_confidence") && !incomplete
	if len(reasons) > 0 {
		out["safe_to_spend"] = float64(0)
		if text(out, "status") == "ok" {
			out["status"] = "warning"
			out["headline"] = "Проверьте данные и обязательства перед расходами"
		}
	}
	if points := docs(out["points"]); len(points) > 0 {
		out["forecast_end"] = points[len(points)-1]["date"]
	}
	for _, gap := range docs(out["gaps"]) {
		gap["probability_reliable"] = out["probability_reliable"]
		dt, _ := day(text(gap, "date"))
		gap["days_left"] = int(dt.Sub(current).Hours() / 24)
	}
}

func reliableProbability(out Doc) bool {
	// Older snapshots can carry the warning without low_confidence or even
	// retain a previously computed true flag. Missing observations take precedence.
	if hasIncompleteHistory(out) {
		return false
	}
	if value, exists := out["probability_reliable"]; exists {
		return value == true
	}
	// Previously saved snapshots have no reliability flag.
	if flag(out, "fallback_used") || flag(out, "low_confidence") {
		return false
	}
	for _, warning := range stringsList(out["warnings"]) {
		if warning == "stale_statement_forecast_starts_after_data_as_of" {
			return false
		}
	}
	return true
}

func hasIncompleteHistory(out Doc) bool {
	for _, warning := range stringsList(out["warnings"]) {
		if warning == "incomplete_history" {
			return true
		}
	}
	return false
}

func stringsList(value any) []string {
	if list, ok := value.([]string); ok {
		return list
	}
	result := []string{}
	if list, ok := value.([]any); ok {
		for _, item := range list {
			if text, ok := item.(string); ok {
				result = append(result, text)
			}
		}
	}
	return result
}
