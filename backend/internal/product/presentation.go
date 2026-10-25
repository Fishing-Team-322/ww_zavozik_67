package product

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/risk"
)

// All HTTP projections use the same snake_case DTO, including simulations.
func (s *Service) gapDocuments(result forecast.Result, reserve float64, explanationPaths ...forecast.Result) []Doc {
	out := []Doc{}
	referenceDay := s.currentDay()
	explanationResult := result
	if len(explanationPaths) > 0 {
		explanationResult = explanationPaths[0]
	}
	for _, gap := range risk.FindGaps(result, domain.Money(reserve)) {
		explanation, causes := explainGap(explanationResult, gap.Date, reserve)
		out = append(out, Doc{"id": gap.ID, "date": gap.Date.Format(domain.DateLayout), "shortfall": money(gap.Shortfall.Float()), "shortfall_p90": money(gap.ShortfallP90.Float()), "probability": gap.Probability, "days_left": int(domain.Day(gap.Date.UTC()).Sub(referenceDay).Hours() / 24), "probability_reliable": !result.Stochastic.FallbackUsed && !result.Stochastic.LowConfidence && referenceDay.Sub(result.AsOf).Hours() <= 7*24 && !result.AsOf.After(referenceDay), "headline": "Остаток может опуститься ниже резерва", "worst_date": explanation["date"], "probability_on_date": explanation["probability_on_first_date"], "explanation": explanation, "causes": causes})
	}
	return out
}
