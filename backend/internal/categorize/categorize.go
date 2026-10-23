// Package categorize — категоризация операций цепочкой: правила → ML/LLM
// для того, что правила не взяли уверенно. Владелец: Бэк 1.
//
// TODO(Бэк 1): расширить правила по ~570 шаблонам назначений из датасета,
// LLM-фолбэк через internal/llm, учёт ручных правок пользователя
// (category_method = user имеет приоритет), замер точности на золотой
// разметке.
package categorize

import (
	"context"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

type Result struct {
	Category   domain.Category
	Confidence float64 // 0..1
	Method     domain.CategoryMethod
}

type Categorizer interface {
	// Categorize возвращает результат на каждую операцию (тот же порядок).
	// Не уверен — Category пустая или Confidence низкий.
	Categorize(ctx context.Context, ops []domain.Operation) ([]Result, error)
}

// Chain передаёт следующему звену только операции, где уверенность
// ниже Threshold.
type Chain struct {
	Steps     []Categorizer
	Threshold float64
}

func (c Chain) Categorize(ctx context.Context, ops []domain.Operation) ([]Result, error) {
	out := make([]Result, len(ops))
	pending := make([]int, len(ops))
	for i := range pending {
		pending[i] = i
	}
	for _, step := range c.Steps {
		if len(pending) == 0 {
			break
		}
		batch := make([]domain.Operation, len(pending))
		for j, i := range pending {
			batch[j] = ops[i]
		}
		res, err := step.Categorize(ctx, batch)
		if err != nil {
			return nil, err
		}
		next := pending[:0]
		for j, i := range pending {
			if res[j].Confidence > out[i].Confidence {
				out[i] = res[j]
			}
			if out[i].Confidence < c.Threshold {
				next = append(next, i)
			}
		}
		pending = next
	}
	for i := range out {
		if out[i].Category == domain.CatUnknown {
			out[i] = Result{Category: domain.CatOther, Method: domain.MethodRule}
		}
	}
	return out, nil
}

// Apply записывает результат в операции.
func Apply(ops []domain.Operation, res []Result) {
	for i := range ops {
		ops[i].Category = res[i].Category
		ops[i].CategoryMethod = res[i].Method
	}
}
