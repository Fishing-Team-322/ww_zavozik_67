package domain

import (
	"log/slog"
	"strconv"
)

// Чувствительные данные (суммы, ИНН, названия контрагентов, назначения)
// имеют свои типы. Они реализуют slog.LogValuer, поэтому в лог попадают
// как [REDACTED], даже если их залогировали по ошибке. Требование кейса:
// «исключить попадание чувствительных данных в логи».

const redacted = "[REDACTED]"

// Money — сумма в рублях.
type Money float64

func (Money) LogValue() slog.Value { return slog.StringValue(redacted) }

// Float — для арифметики и сериализации там, где это осознанно.
func (m Money) Float() float64 { return float64(m) }

func (m Money) String() string { return strconv.FormatFloat(float64(m), 'f', 2, 64) }

type INN string

func (INN) LogValue() slog.Value { return slog.StringValue(redacted) }

// Name — наименование контрагента: у ИП и физлиц это ФИО (152-ФЗ).
type Name string

func (Name) LogValue() slog.Value { return slog.StringValue(redacted) }

type Purpose string

func (Purpose) LogValue() slog.Value { return slog.StringValue(redacted) }

// LogValue операции — только то, что безопасно для отладки.
func (o Operation) LogValue() slog.Value {
	return slog.GroupValue(
		slog.String("id", o.ID),
		slog.String("company_id", o.CompanyID),
		slog.String("date", o.Date.Format(DateLayout)),
		slog.String("direction", string(o.Direction)),
		slog.String("category", string(o.Category)),
	)
}

func (e PlannedEvent) LogValue() slog.Value {
	return slog.GroupValue(
		slog.String("id", e.ID),
		slog.String("company_id", e.CompanyID),
		slog.String("date", e.Date.Format(DateLayout)),
		slog.String("source", string(e.Source)),
		slog.String("status", string(e.Status)),
	)
}

func (c Company) LogValue() slog.Value {
	return slog.GroupValue(slog.String("id", c.ID), slog.String("industry", c.Industry))
}
