// Package risk — разрывы, их вероятность и причины, «можно потратить».
// Владелец: Бэк 2.
//
// TODO(Бэк 2): причины разрыва (waterfall по компонентам), склейка соседних
// дней в один разрыв, headline человеческим языком, ретро
// («мы бы вас предупредили»).
package risk

import (
	"fmt"
	"math"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

type Gap struct {
	ID           string
	Date         time.Time    // первый день, когда остаток ниже резерва
	Shortfall    domain.Money // медиана нехватки в худший день
	ShortfallP90 domain.Money // пессимистичная оценка
	Probability  float64      // доля путей, где остаток ушёл ниже резерва на горизонте
}

type Cause struct {
	Title        string
	Amount       domain.Money
	ComponentKey string
}

// MinProbability — с какой вероятности показываем разрыв.
const MinProbability = 0.1

// FindGaps — пока один разрыв на горизонт: первый день, где доля путей
// ниже резерва >= MinProbability.
func FindGaps(r forecast.Result, reserve domain.Money) []Gap {
	if len(r.Balances) == 0 {
		return nil
	}
	res := reserve.Float()
	paths := float64(len(r.Balances))
	first := -1
	hit := 0
	for _, path := range r.Balances {
		for _, b := range path {
			if b < res {
				hit++
				break
			}
		}
	}
	for d := range r.Dates {
		below := 0
		for p := range r.Balances {
			if r.Balances[p][d] < res {
				below++
			}
		}
		if float64(below)/paths >= MinProbability {
			first = d
			break
		}
	}
	if first < 0 {
		return nil
	}

	p50, p10 := r.Quantile(0.5), r.Quantile(0.1)
	worst50, worst10 := math.Inf(1), math.Inf(1)
	for d := first; d < len(r.Dates); d++ {
		worst50 = math.Min(worst50, p50[d])
		worst10 = math.Min(worst10, p10[d])
	}
	return []Gap{{
		ID:           fmt.Sprintf("gap-%s", r.Dates[first].Format(domain.DateLayout)),
		Date:         r.Dates[first],
		Shortfall:    domain.Money(math.Max(0, res-worst50)),
		ShortfallP90: domain.Money(math.Max(0, res-worst10)),
		Probability:  float64(hit) / paths,
	}}
}

// SafeToSpend — сколько можно потратить сегодня, чтобы в пессимистичном
// сценарии (квантиль q, обычно 0.1) остаток не опустился ниже резерва.
func SafeToSpend(r forecast.Result, reserve domain.Money, q float64) domain.Money {
	low := r.OpeningBalance.Float()
	for _, b := range r.Quantile(q) {
		low = math.Min(low, b)
	}
	return domain.Money(math.Max(0, low-reserve.Float()))
}
