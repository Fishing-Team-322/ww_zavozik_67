// Package scenarios — «что если». Сценарий = цепочка Transform над готовым
// forecast.Result: меняем компоненты и пересчитываем остаток без повторного
// вызова ML. Поэтому drag&drop в календаре пересчитывается мгновенно.
// Владелец: Бэк 2.
//
// TODO(Бэк 2): delay_counterparty, add_expense, scale_fixed_costs,
// move_event, пресеты из кейса.
package scenarios

import (
	"fmt"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/registry"
)

// Step — шаг сценария, как ScenarioStep в api/openapi.yaml.
type Step struct {
	Kind             string
	CounterpartyName string
	DelayDays        int
	Factor           float64
	Amount           float64
	Date             string
	EventID          string
}

type Transform interface {
	Apply(r forecast.Result) (forecast.Result, error)
}

// Factory строит Transform из шага; регистрируется по Kind.
type Factory func(s Step) (Transform, error)

var Kinds = registry.New[Factory]()

// Apply применяет шаги по порядку к копии результата и пересчитывает остаток.
func Apply(r forecast.Result, steps []Step) (forecast.Result, error) {
	out := r.Clone()
	for _, s := range steps {
		f, ok := Kinds.Get(s.Kind)
		if !ok {
			return forecast.Result{}, fmt.Errorf("scenarios: unknown step kind %q", s.Kind)
		}
		t, err := f(s)
		if err != nil {
			return forecast.Result{}, err
		}
		if out, err = t.Apply(out); err != nil {
			return forecast.Result{}, err
		}
	}
	return out, out.Recompute()
}

func init() {
	Kinds.Register("scale_revenue", func(s Step) (Transform, error) {
		if s.Factor < 0 {
			return nil, fmt.Errorf("scale_revenue: factor must be >= 0")
		}
		return scaleRevenue(s.Factor), nil
	})
}

// scaleRevenue — «выручка −20%»: масштабирует поступления стохастической части.
type scaleRevenue float64

func (f scaleRevenue) Apply(r forecast.Result) (forecast.Result, error) {
	for p := range r.Stochastic.Inflow {
		for d := range r.Stochastic.Inflow[p] {
			r.Stochastic.Inflow[p][d] *= float64(f)
		}
	}
	return r, nil
}
