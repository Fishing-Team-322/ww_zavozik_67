// Package ingest — нормализация операций после источника. Владелец: Бэк 1.
//
// Повторы удаляются только при подтверждении остатком. Возвраты сохраняются:
// это реальные движения денег, их схлопывание ломает дневные остатки.
package ingest

import (
	"math"
	"sort"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// DailyFlows раскладывает операции по календарным дням [from, to]: каждый
// день есть в результате. Отсутствие операций само по себе НЕ пропуск.
// Missing ставится только при несовпадении движения с наблюдаемым остатком.
func DailyFlows(ops []domain.Operation, from, to time.Time, keep func(domain.Operation) bool) []domain.DailyFlow {
	flows, _ := DailyFlowsWithDetection(ops, from, to, keep)
	return flows
}

// DailyFlowsWithDetection дополнительно возвращает дату, когда пропуск стал
// известен. Бэктест не должен использовать обнаруженное в будущем расхождение
// при подготовке истории на более раннюю дату.
func DailyFlowsWithDetection(ops []domain.Operation, from, to time.Time, keep func(domain.Operation) bool) ([]domain.DailyFlow, []time.Time) {
	from, to = domain.Day(from), domain.Day(to)
	if to.Before(from) {
		return nil, nil
	}
	n := int(to.Sub(from).Hours()/24) + 1
	out := make([]domain.DailyFlow, n)
	detected := make([]time.Time, n)
	net := make([]float64, n)
	conflict := make([]bool, n)
	for i := range out {
		out[i].Date = from.AddDate(0, 0, i)
	}

	for _, op := range ops {
		i := int(domain.Day(op.Date).Sub(from).Hours() / 24)
		if i < 0 || i >= n {
			continue
		}
		net[i] += op.Signed().Float()
		if op.BalanceEOD != nil {
			b := *op.BalanceEOD
			if out[i].Balance != nil && math.Abs(out[i].Balance.Float()-b.Float()) > 0.011 {
				conflict[i] = true
			}
			out[i].Balance = &b
		}
		if op.Category != domain.CatUnknown {
			if out[i].ByCategory == nil {
				out[i].ByCategory = map[domain.Category]domain.Money{}
			}
			out[i].ByCategory[op.Category] += op.Signed()
		}
		if keep != nil && !keep(op) {
			continue
		}
		if op.Direction == domain.In {
			out[i].Inflow += op.Amount
		} else {
			out[i].Outflow += op.Amount
		}
	}

	last := -1
	movement := 0.0
	for i := 0; i < n; i++ {
		movement += net[i]
		if conflict[i] {
			out[i].Missing = true
			out[i].Balance = nil // conflicting balances cannot anchor the following day
			detected[i] = out[i].Date
			last, movement = -1, 0
			continue
		}
		if out[i].Balance == nil {
			continue
		}
		if last >= 0 && math.Abs(out[i].Balance.Float()-out[last].Balance.Float()-movement) > 0.011 {
			// Не знаем день пропущенной операции: исключаем весь интервал,
			// включая день обнаружения, где тоже могли потерять часть строк.
			for j := last + 1; j <= i; j++ {
				out[j].Missing = true
				detected[j] = out[i].Date
			}
		}
		last = i
		movement = 0
	}
	return out, detected
}

// SortOps — по дате, затем по ID (стабильный порядок для дедупа и тестов).
func SortOps(ops []domain.Operation) {
	sort.SliceStable(ops, func(i, j int) bool {
		if !ops[i].Date.Equal(ops[j].Date) {
			return ops[i].Date.Before(ops[j].Date)
		}
		return ops[i].ID < ops[j].ID
	})
}
