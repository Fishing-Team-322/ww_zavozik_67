package product

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/risk"
)

// All HTTP projections use the same snake_case DTO, including simulations.
func gapDocuments(result forecast.Result, reserve float64) []Doc {
	out := []Doc{}
	for _, gap := range risk.FindGaps(result, domain.Money(reserve)) {
		out = append(out, Doc{"id": gap.ID, "date": gap.Date.Format(domain.DateLayout), "shortfall": money(gap.Shortfall.Float()), "shortfall_p90": money(gap.ShortfallP90.Float()), "probability": gap.Probability, "days_left": int(gap.Date.Sub(result.AsOf).Hours() / 24), "headline": "Остаток может опуститься ниже резерва"})
	}
	return out
}
