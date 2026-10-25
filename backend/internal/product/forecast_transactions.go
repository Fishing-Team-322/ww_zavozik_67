package product

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"time"
)

// Only observations accepted in the daily history may provide invoice/party
// evidence to M6. Reconciliation gaps must not invalidate the entire RPC.
func observedTransactions(cid string, ops []domain.Operation, flows []domain.DailyFlow) []forecast.HistoryTransaction {
	observed := make(map[time.Time]bool, len(flows))
	for _, flow := range flows {
		observed[domain.Day(flow.Date)] = !flow.Missing
	}
	out := []forecast.HistoryTransaction{}
	for _, op := range ops {
		if !observed[domain.Day(op.Date)] {
			continue
		}
		category := op.Category
		if category == domain.CatUnknown {
			category = domain.CatOther
		}
		ref := cpRef(cid, Doc{"counterparty_inn": string(op.CounterpartyINN), "counterparty_name": string(op.CounterpartyName)})
		out = append(out, forecast.HistoryTransaction{ID: op.ID, Date: op.Date, Amount: op.Amount, Direction: op.Direction, Category: category, CounterpartyID: text(ref, "id"), Purpose: op.Purpose})
	}
	return out
}
