package importcsv

import (
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"
	"unicode/utf8"

	"golang.org/x/text/encoding/charmap"
	"golang.org/x/text/transform"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/money"
)

// Mapping maps canonical field names to input column headers.
type Mapping struct {
	Category  string            `json:"category"` // actual, invoice, manual_plan
	Encoding  string            `json:"encoding"` // utf-8 or windows-1251
	Delimiter string            `json:"delimiter"`
	Columns   map[string]string `json:"columns"`
}

type RowIssue struct {
	Row     int    `json:"row"`
	Field   string `json:"field"`
	Message string `json:"message"`
}

type Preview struct {
	Batch  contracts.ImportBatch `json:"batch"`
	Issues []RowIssue            `json:"issues"`
}

func Parse(reader io.Reader, companyID string, mapping Mapping) (Preview, error) {
	var result Preview
	if companyID == "" || (mapping.Category != "actual" && mapping.Category != "invoice" && mapping.Category != "manual_plan") {
		return result, errors.New("company_id and valid category required")
	}
	var source io.Reader = io.LimitReader(reader, 10<<20+1)
	switch strings.ToLower(mapping.Encoding) {
	case "", "utf-8", "utf8":
	case "windows-1251", "cp1251":
		source = transform.NewReader(source, charmap.Windows1251.NewDecoder())
	default:
		return result, errors.New("unsupported CSV encoding")
	}
	data, err := io.ReadAll(source)
	if err != nil || len(data) > 10<<20 || !utf8.Valid(data) {
		return result, errors.New("CSV is too large or invalidly encoded")
	}
	if len(data) >= 3 && string(data[:3]) == "\xef\xbb\xbf" {
		data = data[3:]
	}
	delimiter := ';'
	if mapping.Delimiter != "" {
		if len([]rune(mapping.Delimiter)) != 1 {
			return result, errors.New("invalid CSV delimiter")
		}
		delimiter = []rune(mapping.Delimiter)[0]
	}
	if delimiter != ';' && delimiter != ',' && delimiter != '\t' {
		return result, errors.New("unsupported CSV delimiter")
	}
	cr := csv.NewReader(strings.NewReader(string(data)))
	cr.Comma = delimiter
	cr.FieldsPerRecord = -1
	cr.TrimLeadingSpace = true
	headers, err := cr.Read()
	if err != nil {
		return result, errors.New("CSV header missing")
	}
	index := make(map[string]int)
	for i, h := range headers {
		index[strings.TrimSpace(h)] = i
	}
	required := []string{"date", "amount", "direction"}
	if mapping.Category == "actual" {
		required = append(required, "executed")
	}
	for _, field := range required {
		name := mapping.Columns[field]
		if name == "" {
			name = field
		}
		if _, ok := index[name]; !ok {
			return result, fmt.Errorf("required CSV column %s missing", field)
		}
	}
	batch := contracts.NewBatchFor(companyID, "csv_"+mapping.Category, "import")
	batch.ImportedAt = time.Now().UTC().Format(time.RFC3339)
	hash := sha256.Sum256(data)
	batch.ImportID = hex.EncodeToString(hash[:])
	issues := make([]RowIssue, 0)
	for rowNum := 2; ; rowNum++ {
		row, err := cr.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			issues = append(issues, RowIssue{rowNum, "csv", "malformed row"})
			batch.Stats.Rejected++
			continue
		}
		batch.Stats.Parsed++
		get := func(field string) string {
			name := mapping.Columns[field]
			if name == "" {
				name = field
			}
			i, ok := index[name]
			if !ok || i >= len(row) {
				return ""
			}
			return strings.TrimSpace(row[i])
		}
		date, err := parseDate(get("date"))
		if err != nil {
			issues = append(issues, RowIssue{rowNum, "date", "invalid date"})
			batch.Stats.Rejected++
			continue
		}
		amount, err := money.Parse(strings.ReplaceAll(get("amount"), " ", ""))
		if err != nil || amount == 0 {
			issues = append(issues, RowIssue{rowNum, "amount", "invalid positive amount"})
			batch.Stats.Rejected++
			continue
		}
		direction := get("direction")
		if direction != "in" && direction != "out" {
			issues = append(issues, RowIssue{rowNum, "direction", "expected in or out"})
			batch.Stats.Rejected++
			continue
		}
		id := get("external_id")
		if id == "" {
			rowHash := sha256.Sum256([]byte(strings.Join(row, "\x00")))
			id = hex.EncodeToString(rowHash[:])
		}
		if mapping.Category == "actual" {
			if get("executed") != "true" {
				issues = append(issues, RowIssue{rowNum, "executed", "actual requires explicit true"})
				batch.Stats.Rejected++
				continue
			}
			op := contracts.Operation{ExternalID: id, DedupKey: "csv_actual:" + id, Date: date, AmountKopecks: amount, Direction: direction, CounterpartyINN: get("counterparty_inn"), CounterpartyName: get("counterparty_name"), Purpose: get("title"), SourceKind: "csv_actual", Account: get("account"), Executed: true}
			batch.Operations = append(batch.Operations, op)
		} else {
			due := get("due_date")
			var duePtr *string
			quality := "unknown"
			if due != "" {
				parsed, e := parseDate(due)
				if e != nil {
					issues = append(issues, RowIssue{rowNum, "due_date", "invalid date"})
					batch.Stats.Rejected++
					continue
				}
				duePtr = &parsed
				quality = "user_supplied"
			}
			kind := "csv_" + mapping.Category
			plan := contracts.PlannedEvent{ExternalID: id, Date: date, AmountKopecks: amount, Direction: direction, Title: get("title"), SourceKind: kind, Status: "expected", DocumentNumber: get("document_number"), DocumentDate: date, DueDate: duePtr, DateQuality: quality, TotalKopecks: amount, RemainingKopecks: amount, Currency: "RUB", CounterpartyINN: get("counterparty_inn"), LinkStatus: "manual_unmatched", ForecastEligible: duePtr != nil, DataMode: "import", ObservedAt: batch.ImportedAt}
			batch.PlannedEvents = append(batch.PlannedEvents, plan)
		}
		batch.Stats.Accepted++
	}
	result.Batch = batch
	result.Issues = issues
	return result, nil
}

func parseDate(s string) (string, error) {
	for _, layout := range []string{"2006-01-02", "02.01.2006"} {
		if d, e := time.Parse(layout, s); e == nil {
			return d.Format("2006-01-02"), nil
		}
	}
	return "", errors.New("invalid date")
}
