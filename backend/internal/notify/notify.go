// Package notify — каналы уведомлений. Владелец: Бэк 3.
//
// TODO(Бэк 3): in_app (таблица alerts), telegram (cmd/bot привязывает чат).
package notify

import (
	"context"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/registry"
)

type Severity string

const (
	Info    Severity = "info"
	Warning Severity = "warning"
	Danger  Severity = "danger"
)

type Alert struct {
	ID        string
	CompanyID string
	UserID    string
	CreatedAt time.Time
	Severity  Severity
	Title     string
	Body      string
	GapID     string
}

type Notifier interface {
	Name() string
	Send(ctx context.Context, a Alert) error
}

var Channels = registry.New[Notifier]()
