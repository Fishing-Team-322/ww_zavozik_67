// Package recurring — поиск регулярных платежей и их проекция на горизонт.
// Владелец: Бэк 1 (поиск), Бэк 2 использует проекцию в прогнозе.
//
// TODO(Бэк 1): детектор по (контрагент или шаблон назначения, период,
// сумма ± разброс): зарплата аванс + расчёт, ЕНП 28-го, аренда, кредиты,
// лизинг, связь. Проекция с переносом на рабочий день по производственному
// календарю РФ.
package recurring

import (
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

type Detector interface {
	Detect(ops []domain.Operation) []domain.RecurringPattern
}

type Projector interface {
	// Project раскладывает паттерны на даты в (from, to].
	Project(patterns []domain.RecurringPattern, from, to time.Time) []forecast.ComponentFlow
}
