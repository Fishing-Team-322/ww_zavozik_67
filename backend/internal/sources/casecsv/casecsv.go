// Package casecsv — парсер формата датасета кейса (statements/Cxxx.csv,
// all_operations.csv): UTF-8 с BOM, разделитель «;», ИНН строкой.
package casecsv

import (
	"bytes"
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"io"
	"math"
	"strconv"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/sources"
)

func init() { sources.Parsers.Register(Kind, Parser{}) }

const Kind = "case_csv"

var header = []string{"company_id", "operation_id", "operation_date", "amount", "direction",
	"counterparty_inn", "counterparty_name", "payment_purpose", "balance_eod"}

type Parser struct{}

func (Parser) Kind() domain.SourceKind { return domain.SrcUpload }

func (Parser) Detect(filename string, head []byte) bool {
	head = bytes.TrimPrefix(head, []byte("\uFEFF"))
	return strings.HasSuffix(strings.ToLower(filename), ".csv") &&
		bytes.HasPrefix(head, []byte(strings.Join(header[:3], ";")))
}

// Parse читает файл. companyID пустой — берём из колонки company_id
// (all_operations.csv содержит все компании сразу).
func (Parser) Parse(_ context.Context, companyID string, r io.Reader) (sources.Batch, error) {
	cr := csv.NewReader(r)
	cr.Comma = ';'
	cr.FieldsPerRecord = len(header)
	cr.ReuseRecord = true

	first, err := cr.Read()
	if err != nil {
		return sources.Batch{}, fmt.Errorf("casecsv: header: %w", err)
	}
	first[0] = strings.TrimPrefix(first[0], "\uFEFF")
	for i, h := range header {
		if first[i] != h {
			return sources.Batch{}, fmt.Errorf("casecsv: column %d: want %q", i, h)
		}
	}

	var ops []domain.Operation
	for line := 2; ; line++ {
		rec, err := cr.Read()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return sources.Batch{}, fmt.Errorf("casecsv: line %d: %w", line, err)
		}
		op, err := parseRecord(rec)
		if err != nil {
			return sources.Batch{}, fmt.Errorf("casecsv: line %d: %w", line, err)
		}
		if companyID != "" {
			op.CompanyID = companyID
		}
		ops = append(ops, op)
	}
	return sources.Batch{Operations: ops}, nil
}

func parseRecord(rec []string) (domain.Operation, error) {
	date, err := time.Parse(domain.DateLayout, rec[2])
	if err != nil {
		return domain.Operation{}, fmt.Errorf("operation_date: invalid date, want %s", domain.DateLayout)
	}
	amount, err := parseNumber("amount", rec[3])
	if err != nil {
		return domain.Operation{}, err
	}
	if amount < 0 {
		return domain.Operation{}, errors.New("amount: must be non-negative")
	}
	var dir domain.Direction
	switch rec[4] {
	case "Поступление":
		dir = domain.In
	case "Списание":
		dir = domain.Out
	default:
		return domain.Operation{}, fmt.Errorf("direction: want %q or %q", "Поступление", "Списание")
	}
	op := domain.Operation{
		ID:               rec[1],
		CompanyID:        rec[0],
		Date:             date,
		Amount:           domain.Money(amount),
		Direction:        dir,
		CounterpartyINN:  domain.INN(rec[5]),
		CounterpartyName: domain.Name(rec[6]),
		Purpose:          domain.Purpose(rec[7]),
		Source:           domain.SrcUpload,
	}
	if rec[8] != "" {
		b, err := parseNumber("balance_eod", rec[8])
		if err != nil {
			return domain.Operation{}, err
		}
		m := domain.Money(b)
		op.BalanceEOD = &m
	}
	return op, nil
}

// parseNumber разбирает числовую ячейку и возвращает диагностику без самого
// значения: strconv.NumError хранит исходную строку, а суммы — чувствительные
// данные, которым не место в логах. Отрицательный остаток допустим, знак
// суммы проверяет parseRecord.
func parseNumber(field, cell string) (float64, error) {
	v, err := strconv.ParseFloat(cell, 64)
	if err != nil {
		var numErr *strconv.NumError
		if errors.As(err, &numErr) && errors.Is(numErr.Err, strconv.ErrRange) {
			return 0, fmt.Errorf("%s: out of range", field)
		}
		return 0, fmt.Errorf("%s: not a number", field)
	}
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return 0, fmt.Errorf("%s: must be finite", field)
	}
	return v, nil
}
