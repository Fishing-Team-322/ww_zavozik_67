// Package ingest — нормализация операций после источника. Владелец: Бэк 1.
//
// TODO(Бэк 1):
//   - Dedup: дубли ловим сверкой с остатком — если balance_eod[t] −
//     balance_eod[t−1] ≠ сумме за день, а лишняя строка ровно объясняет
//     расхождение, это дубль (в датасете так находятся все 21 дубль);
//   - флаг внутренних переводов (свои средства, займы учредителя);
//   - возвраты ошибочных платежей — схлопывать с исходным платежом.
package ingest

import (
	"sort"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// MinGapDays — сколько календарных дней без операций считаем пропуском
// в выписке, а не просто тихим периодом.
const MinGapDays = 10

// DailyFlows раскладывает операции по календарным дням [from, to]: каждый
// день есть в результате, выходные — нули. Дни внутри пропуска
// (>= MinGapDays без операций) помечены Missing. keep решает, какие
// операции учитывать (nil — все).
func DailyFlows(ops []domain.Operation, from, to time.Time, keep func(domain.Operation) bool) []domain.DailyFlow {
	from, to = domain.Day(from), domain.Day(to)
	if to.Before(from) {
		return nil
	}
	n := int(to.Sub(from).Hours()/24) + 1
	out := make([]domain.DailyFlow, n)
	for i := range out {
		out[i].Date = from.AddDate(0, 0, i)
	}

	active := make([]bool, n)
	for _, op := range ops {
		i := int(domain.Day(op.Date).Sub(from).Hours() / 24)
		if i < 0 || i >= n {
			continue
		}
		active[i] = true
		if op.BalanceEOD != nil {
			b := *op.BalanceEOD
			out[i].Balance = &b
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
	for i := 0; i <= n; i++ {
		if i < n && !active[i] {
			continue
		}
		if last >= 0 && i-last-1 >= MinGapDays {
			for j := last + 1; j < i; j++ {
				out[j].Missing = true
			}
		}
		last = i
	}
	return out
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
