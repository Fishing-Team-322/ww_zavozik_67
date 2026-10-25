package product

import (
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func composedEvent(event Doc) bool {
	return flag(event, "additional") || flag(event, "_recurring_replacement")
}

// Preserve the detected schedule before user edits. The business-flow model
// already includes this estimate; compose the confirmed replacement as a delta.
func rememberRecurringBaseline(pattern Doc) {
	if text(pattern, "origin") != "detected" {
		return
	}
	for baseline, current := range map[string]string{"baseline_amount": "amount", "baseline_direction": "direction", "baseline_period": "period", "baseline_day_of_month": "day_of_month", "baseline_next_date": "next_date"} {
		if _, exists := pattern[baseline]; !exists {
			pattern[baseline] = pattern[current]
		}
	}
}

func recurringBaselineComponents(patterns []Doc, asOf time.Time, horizon int) ([]forecast.ComponentFlow, map[string]bool) {
	components := []forecast.ComponentFlow{}
	covered := map[string]bool{}
	for _, pattern := range patterns {
		if text(pattern, "origin") != "detected" || !flag(pattern, "active") || !flag(pattern, "confirmed") {
			continue
		}
		rememberRecurringBaseline(pattern)
		start, err := day(date(pattern["baseline_next_date"]))
		if err != nil {
			continue
		}
		id := text(pattern, "id")
		covered[id] = true
		amount := number(pattern, "baseline_amount")
		direction := text(pattern, "baseline_direction")
		if direction == "in" {
			amount = -amount
		}
		end := asOf.AddDate(0, 0, horizon)
		for count := 0; count < 4000 && !start.After(end); count++ {
			if start.After(asOf) {
				components = append(components, forecast.ComponentFlow{Date: start, Key: "recurring:baseline:" + direction + ":" + id + ":" + start.Format(domain.DateLayout), Title: "Замена исходного регулярного плана: " + text(pattern, "title"), Amount: domain.Money(amount), Source: "recurring"})
			}
			next := nextOccurrence(start, text(pattern, "baseline_period"), int(number(pattern, "baseline_day_of_month")))
			if !next.After(start) {
				break
			}
			start = next
		}
	}
	return components, covered
}
