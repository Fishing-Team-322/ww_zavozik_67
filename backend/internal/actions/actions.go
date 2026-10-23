// Package actions — рекомендации, как закрыть разрыв, с пересчитанным
// эффектом (через scenarios). Владелец: Бэк 2.
//
// TODO(Бэк 2): remind_client (просроченные УПД + текст письма через llm),
// shift_supplier_payment, overdraft (стоимость в процентах), split_payment.
package actions

import (
	"context"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/registry"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/risk"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/scenarios"
)

type Effect struct {
	ClosesGap      bool
	NewProbability float64
	NewShortfall   domain.Money
}

type Action struct {
	ID           string
	Kind         string
	Title        string
	Description  string
	Cost         domain.Money
	Steps        []scenarios.Step // как действие меняет прогноз
	Effect       Effect
	DraftMessage string
}

type Context struct {
	Company  domain.Company
	Forecast forecast.Result
	History  []domain.Operation
	Planned  []domain.PlannedEvent
}

type Generator interface {
	Propose(ctx context.Context, gap risk.Gap, c Context) ([]Action, error)
}

var Generators = registry.New[Generator]()
