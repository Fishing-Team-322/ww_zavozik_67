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
			return sources.Batch{}, fmt.Errorf("casecsv: column %d: want %q, got %q", i, h, first[i])
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
		return domain.Operation{}, fmt.Errorf("operation_date: %w", err)
	}
	amount, err := strconv.ParseFloat(rec[3], 64)
	if err != nil {
		return domain.Operation{}, fmt.Errorf("amount: %w", err)
	}
	var dir domain.Direction
	switch rec[4] {
	case "Поступление":
		dir = domain.In
	case "Списание":
		dir = domain.Out
	default:
		return domain.Operation{}, fmt.Errorf("direction: unknown %q", rec[4])
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
		b, err := strconv.ParseFloat(rec[8], 64)
		if err != nil {
			return domain.Operation{}, fmt.Errorf("balance_eod: %w", err)
		}
		m := domain.Money(b)
		op.BalanceEOD = &m
	}
	return op, nil
}
