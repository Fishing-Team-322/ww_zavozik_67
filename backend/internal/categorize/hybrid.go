package categorize

import (
	"context"
	"fmt"
	"math"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// Hybrid lets a confident ML result correct a broad legacy regexp. Manual
// labels always win. Rules remain available when ML is unavailable or abstains.
// The threshold is explicit and must be evaluated on calibration data.
// Chain remains unchanged for existing callers; adopt Hybrid deliberately.
type Hybrid struct {
	ML              Categorizer
	Rules           Categorizer
	MinMLConfidence float64
}

func (h Hybrid) Categorize(ctx context.Context, ops []domain.Operation) ([]Result, error) {
	rules := h.Rules
	if rules == nil {
		rules = DefaultRules
	}
	base, err := rules.Categorize(ctx, ops)
	if err != nil {
		return nil, err
	}
	if len(base) != len(ops) {
		return nil, fmt.Errorf("categorize: invalid rule result length")
	}
	threshold := h.MinMLConfidence
	if threshold == 0 {
		threshold = .8
	}
	if math.IsNaN(threshold) || threshold < 0 || threshold > 1 {
		return nil, fmt.Errorf("categorize: confidence threshold must be in [0, 1]")
	}
	pending := make([]domain.Operation, 0, len(ops))
	indices := make([]int, 0, len(ops))
	for i, op := range ops {
		if op.CategoryMethod == domain.MethodUser && knownCategory[op.Category] {
			base[i] = Result{Category: op.Category, Confidence: 1, Method: domain.MethodUser}
		} else {
			pending = append(pending, op)
			indices = append(indices, i)
		}
	}
	if h.ML != nil && len(pending) > 0 {
		learned, e := h.ML.Categorize(ctx, pending)
		if e != nil {
			return nil, e
		}
		if len(learned) != len(pending) {
			return nil, fmt.Errorf("categorize: invalid ML result length")
		}
		for j, i := range indices {
			p := learned[j]
			if knownCategory[p.Category] && p.Category != domain.CatOther && p.Confidence >= threshold {
				base[i] = p
			}
			if base[i].Category == domain.CatUnknown && knownCategory[p.Category] {
				base[i] = p
			}
		}
	}
	for i := range base {
		if base[i].Category == domain.CatUnknown {
			base[i] = Result{Category: domain.CatOther, Method: domain.MethodRule}
		}
	}
	return base, nil
}
