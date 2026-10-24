package dataset

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"testing"
)

func TestFillBalanceOnlyCarriesThroughQuietKnownDays(t *testing.T) {
	b := domain.Money(100)
	for _, movement := range []domain.DailyFlow{
		{Inflow: 50}, {Outflow: 50}, {Missing: true},
		{ByCategory: map[domain.Category]domain.Money{domain.CatOwnTransfer: 50}},
	} {
		flows := []domain.DailyFlow{{Balance: &b}, {}, movement, {}, {Balance: &b}, {}}
		FillBalance(flows)
		if flows[1].Balance == nil || *flows[1].Balance != b || flows[2].Balance != nil || flows[3].Balance != nil || flows[5].Balance == nil {
			t.Fatalf("invalid balance carry for %+v: %+v", movement, flows)
		}
	}
}
