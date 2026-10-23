// Package events — плановые события, которых ещё нет в выписке: налоговый
// календарь, открытые УПД, договоры, ручной ввод. Владелец: Бэк 2.
//
// TODO(Бэк 2): tax_calendar (ЕНП 28-го, уведомления 25-го, авансы УСН,
// НДС по кварталам), open_invoices (УПД без оплаты + средняя отсрочка
// клиента), manual, Parser фразы через internal/llm.
package events

import (
	"context"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/registry"
)

// Provider выдаёт ожидаемые события компании на интервале.
type Provider interface {
	Name() string
	Events(ctx context.Context, c domain.Company, history []domain.Operation, from, to time.Time) ([]domain.PlannedEvent, error)
}

var Providers = registry.New[Provider]()

// Parser превращает фразу «клиент обещал 300к 20-го» в черновик события.
type Parser interface {
	Parse(ctx context.Context, c domain.Company, text string, today time.Time) (domain.PlannedEvent, error)
}
