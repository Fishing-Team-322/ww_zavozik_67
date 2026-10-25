package product

import (
	"context"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/llm"
)

func (s *Service) explainCashflowActions(ctx context.Context, actions []Doc) {
	if s.CashflowNarrator == nil {
		return
	}
	pending, facts := []Doc{}, []llm.CashflowFact{}
	for _, action := range actions {
		if text(action, "explanation_source") == "llm" {
			continue
		}
		effect := action["effect"].(Doc)
		pending = append(pending, action)
		facts = append(facts, llm.CashflowFact{Kind: text(action, "kind"), ClosesGap: flag(effect, "closes_gap"), Improves: number(effect, "shortfall_p90_reduction") > 0 || number(effect, "shortfall_reduction") > 0, BeyondHorizon: flag(action, "deferred_beyond_horizon")})
	}
	if len(facts) == 0 {
		return
	}
	explanations, err := s.CashflowNarrator.Explain(ctx, facts)
	if err != nil {
		// Rate limits, missing model or provider failure do not remove the
		// calculated recommendations or their built-in explanations.
		return
	}
	for i, explanation := range explanations {
		pending[i]["explanation"], pending[i]["explanation_source"] = explanation, "llm"
	}
}
