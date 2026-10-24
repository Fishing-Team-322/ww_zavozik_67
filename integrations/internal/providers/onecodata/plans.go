package onecodata

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/money"
)

// PlanConfig maps a particular published 1C configuration. Entity and field
// names must be discovered from that infobase's $metadata before live use.
type PlanConfig struct {
	BaseURL         string            `json:"base_url"`
	CompanyID       string            `json:"company_id"`
	DataMode        string            `json:"data_mode"`
	OrganizationIDs []string          `json:"organization_ids"`
	RUBCurrencyIDs  []string          `json:"rub_currency_ids,omitempty"`
	AccountMap      map[string]string `json:"account_map,omitempty"`
	Invoices        []InvoiceSource   `json:"invoices"`
	Payments        []PaymentSource   `json:"payments"`
}

type InvoiceSource struct {
	EntitySet string        `json:"entity_set"`
	Direction string        `json:"direction"`
	Fields    InvoiceFields `json:"fields"`
}

type InvoiceFields struct {
	ExternalID      string `json:"external_id"`
	Number          string `json:"number"`
	DocumentDate    string `json:"document_date"`
	DueDate         string `json:"due_date,omitempty"`
	Amount          string `json:"amount"`
	Posted          string `json:"posted"`
	Deleted         string `json:"deleted,omitempty"`
	OrganizationKey string `json:"organization_key"`
	CurrencyKey     string `json:"currency_key,omitempty"`
	AccountKey      string `json:"account_key,omitempty"`
	CounterpartyINN string `json:"counterparty_inn,omitempty"`
	SourceVersion   string `json:"source_version,omitempty"`
}

type PaymentSource struct {
	EntitySet        string         `json:"entity_set"`
	InvoiceEntitySet string         `json:"invoice_entity_set"`
	Fields           PaymentFields  `json:"fields"`
	Parent           *PaymentParent `json:"parent,omitempty"`
}

// 1C document detail collections normally do not expose Posted themselves.
// Parent maps the bank document whose Ref_Key is present on each detail row.
type PaymentParent struct {
	EntitySet       string `json:"entity_set"`
	ExternalID      string `json:"external_id"`
	Posted          string `json:"posted"`
	Unconfirmed     string `json:"unconfirmed,omitempty"`
	OrganizationKey string `json:"organization_key"`
}

type PaymentFields struct {
	ExternalID  string `json:"external_id"`
	LineNumber  string `json:"line_number"`
	InvoiceKey  string `json:"invoice_key"`
	Amount      string `json:"amount"`
	Posted      string `json:"posted,omitempty"`
	Unconfirmed string `json:"unconfirmed,omitempty"`
}

func LoadPlanConfig(path string) (PlanConfig, error) {
	var cfg PlanConfig
	if path == "" {
		return cfg, ErrConfig
	}
	f, err := os.Open(path)
	if err != nil {
		return cfg, ErrConfig
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, (64<<10)+1))
	if err != nil || len(data) > 64<<10 {
		return cfg, ErrConfig
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if dec.Decode(&cfg) != nil || dec.Decode(new(any)) != io.EOF || cfg.Validate() != nil {
		return PlanConfig{}, ErrConfig
	}
	return cfg, nil
}

func (c PlanConfig) Validate() error {
	u, err := url.Parse(c.BaseURL)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || !strings.HasSuffix(u.Path, "/") ||
		(u.Scheme != "https" && (u.Scheme != "http" || !isLoopback(u.Hostname()))) ||
		c.CompanyID == "" || len(c.CompanyID) > 128 || strings.TrimSpace(c.CompanyID) != c.CompanyID ||
		(c.DataMode != "live" && c.DataMode != "mock" && c.DataMode != "fixture") ||
		len(c.OrganizationIDs) == 0 || len(c.OrganizationIDs) > 32 || len(c.RUBCurrencyIDs) > 8 || len(c.Invoices) == 0 || len(c.Invoices) > 8 || len(c.Payments) > 8 ||
		(c.DataMode == "live" && len(c.RUBCurrencyIDs) == 0) {
		return ErrConfig
	}
	for _, id := range c.OrganizationIDs {
		if id == "" || len(id) > 128 {
			return ErrConfig
		}
	}
	for _, id := range c.RUBCurrencyIDs {
		if id == "" || len(id) > 128 {
			return ErrConfig
		}
	}
	for key, account := range c.AccountMap {
		if key == "" || len(key) > 128 || len(account) != 20 || !digits(account) {
			return ErrConfig
		}
	}
	invoiceSets := map[string]bool{}
	for _, invoice := range c.Invoices {
		f := invoice.Fields
		if !validEntity(invoice.EntitySet) || invoiceSets[invoice.EntitySet] || (invoice.Direction != "in" && invoice.Direction != "out") ||
			!allFields(f.ExternalID, f.Number, f.DocumentDate, f.Amount, f.Posted, f.OrganizationKey) ||
			!optionalFields(f.DueDate, f.Deleted, f.AccountKey, f.CurrencyKey, f.CounterpartyINN, f.SourceVersion) ||
			(c.DataMode == "live" && f.CurrencyKey == "") {
			return ErrConfig
		}
		invoiceSets[invoice.EntitySet] = true
	}
	for _, payment := range c.Payments {
		f := payment.Fields
		if !validEntity(payment.EntitySet) || !invoiceSets[payment.InvoiceEntitySet] ||
			!allFields(f.ExternalID, f.LineNumber, f.InvoiceKey, f.Amount) || !optionalFields(f.Posted, f.Unconfirmed) ||
			(f.Posted == "" && payment.Parent == nil) {
			return ErrConfig
		}
		if payment.Parent != nil {
			p := payment.Parent
			if !validEntity(p.EntitySet) || !allFields(p.ExternalID, p.Posted, p.OrganizationKey) || !optionalFields(p.Unconfirmed) {
				return ErrConfig
			}
		}
	}
	return nil
}

func allFields(fields ...string) bool {
	for _, field := range fields {
		if !validField(field) {
			return false
		}
	}
	return true
}

func optionalFields(fields ...string) bool {
	for _, field := range fields {
		if field != "" && !validField(field) {
			return false
		}
	}
	return true
}

// FetchPlans reads a complete bounded snapshot before returning any event for
// storage. Only explicit invoice references in payment detail rows are used.
func (c Client) FetchPlans(ctx context.Context, cfg PlanConfig) (contracts.ImportBatch, error) {
	batch := contracts.NewBatchFor(cfg.CompanyID, contracts.SourceOneCOData, "pull")
	if cfg.Validate() != nil || (c.Username == "" && c.Password != "") {
		return batch, ErrConfig
	}
	if _, ok := ctx.Deadline(); !ok {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, 30*time.Second)
		defer cancel()
	}
	client := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if c.HTTP != nil {
		client.Transport = c.HTTP.Transport
	}
	paid := map[string]int64{}
	seenPayment := map[string]bool{}
	organizations := map[string]bool{}
	for _, id := range cfg.OrganizationIDs {
		organizations[id] = true
	}
	for _, source := range cfg.Payments {
		approvedParents := map[string]bool{}
		if source.Parent != nil {
			parents, err := c.planRows(ctx, client, cfg.BaseURL, source.Parent.EntitySet)
			if err != nil {
				return batch, err
			}
			p := source.Parent
			for _, row := range parents {
				if organizations[getString(row, p.OrganizationKey)] && getString(row, p.Posted) == "true" &&
					(p.Unconfirmed == "" || getString(row, p.Unconfirmed) != "true") {
					approvedParents[getString(row, p.ExternalID)] = true
				}
			}
		}
		rows, err := c.planRows(ctx, client, cfg.BaseURL, source.EntitySet)
		if err != nil {
			return batch, err
		}
		for _, row := range rows {
			f := source.Fields
			if source.Parent != nil && !approvedParents[getString(row, f.ExternalID)] {
				continue
			}
			if f.Posted != "" && getString(row, f.Posted) != "true" {
				continue
			}
			if f.Unconfirmed != "" && getString(row, f.Unconfirmed) == "true" {
				continue
			}
			invoiceID, paymentID, line := getString(row, f.InvoiceKey), getString(row, f.ExternalID), getString(row, f.LineNumber)
			if invoiceID == "" || paymentID == "" || line == "" {
				continue
			}
			amount, err := money.Parse(getString(row, f.Amount))
			if err != nil || amount == 0 {
				return batch, ErrUpstream
			}
			paymentKey := source.EntitySet + "\x00" + paymentID + "\x00" + line
			if seenPayment[paymentKey] {
				continue
			}
			seenPayment[paymentKey] = true
			key := source.InvoiceEntitySet + "\x00" + invoiceID
			if paid[key] > int64(^uint64(0)>>1)-amount {
				return batch, ErrUpstream
			}
			paid[key] += amount
		}
	}
	linked := map[string]bool{}
	for _, source := range cfg.Payments {
		linked[source.InvoiceEntitySet] = true
	}
	seenInvoice := map[string]bool{}
	now := time.Now().UTC()
	for _, source := range cfg.Invoices {
		rows, err := c.planRows(ctx, client, cfg.BaseURL, source.EntitySet)
		if err != nil {
			return batch, err
		}
		for _, row := range rows {
			batch.Stats.Parsed++
			f := source.Fields
			if !organizations[getString(row, f.OrganizationKey)] {
				batch.Stats.Rejected++
				batch.Issues = append(batch.Issues, contracts.Issue{Code: "foreign_organization", Section: batch.Stats.Parsed, Message: "OData invoice was skipped"})
				continue
			}
			id := getString(row, f.ExternalID)
			key := source.EntitySet + "\x00" + id
			if id != "" && seenInvoice[key] {
				batch.Stats.Duplicates++
				continue
			}
			event, code := mapInvoice(row, source, cfg, linked[source.EntitySet], paid[key], now)
			if code != "" {
				batch.Stats.Rejected++
				batch.Issues = append(batch.Issues, contracts.Issue{Code: code, Section: batch.Stats.Parsed, Message: "OData invoice was skipped"})
				continue
			}
			seenInvoice[key] = true
			batch.PlannedEvents = append(batch.PlannedEvents, event)
			batch.Stats.Accepted++
		}
	}
	return batch, nil
}

func (c Client) planRows(ctx context.Context, client *http.Client, root, entity string) ([]map[string]any, error) {
	base, _ := url.Parse(strings.TrimRight(root, "/") + "/" + url.PathEscape(entity))
	query := base.Query()
	query.Set("$format", "json")
	query.Set("$top", "200")
	base.RawQuery = query.Encode()
	next := base.String()
	visited := map[string]bool{}
	rows := make([]map[string]any, 0)
	for page := 0; next != ""; page++ {
		if page >= maxPages || visited[next] {
			return nil, ErrLimit
		}
		visited[next] = true
		part, link, err := c.readPage(ctx, client, next)
		if err != nil {
			return nil, err
		}
		if len(rows)+len(part) > maxRecords {
			return nil, ErrLimit
		}
		rows = append(rows, part...)
		if link == "" {
			break
		}
		u, err := base.Parse(link)
		if err != nil || u.Scheme != base.Scheme || u.Host != base.Host || u.Path != base.Path || u.User != nil || u.Fragment != "" {
			return nil, ErrUpstream
		}
		next = u.String()
	}
	return rows, nil
}

func mapInvoice(row map[string]any, source InvoiceSource, cfg PlanConfig, linked bool, paid int64, now time.Time) (contracts.PlannedEvent, string) {
	f := source.Fields
	id, number := getString(row, f.ExternalID), getString(row, f.Number)
	if id == "" || number == "" {
		return contracts.PlannedEvent{}, "missing_identity"
	}
	if getString(row, f.Posted) != "true" && getString(row, f.Deleted) != "true" {
		return contracts.PlannedEvent{}, "not_posted"
	}
	docDate, err := parseDate(getString(row, f.DocumentDate))
	if err != nil {
		return contracts.PlannedEvent{}, "invalid_document_date"
	}
	total, err := money.Parse(getString(row, f.Amount))
	if err != nil || total == 0 {
		return contracts.PlannedEvent{}, "invalid_amount"
	}
	event := contracts.PlannedEvent{
		ExternalID: source.EntitySet + ":" + id, Date: docDate, DocumentDate: docDate,
		DocumentNumber: number, AmountKopecks: total, TotalKopecks: total, RemainingKopecks: total,
		Direction: source.Direction, Title: "Счёт №" + number, SourceKind: contracts.SourceOneCOData,
		Status: "expected", Currency: "RUB", DateQuality: "unknown", LinkStatus: "unmatched",
		RawReference: id, DataMode: cfg.DataMode, ObservedAt: now.Format(time.RFC3339Nano),
		CounterpartyINN: getString(row, f.CounterpartyINN), SourceVersion: getString(row, f.SourceVersion),
	}
	if f.AccountKey != "" {
		key := getString(row, f.AccountKey)
		account, ok := cfg.AccountMap[key]
		if !ok {
			return contracts.PlannedEvent{}, "unknown_account"
		}
		event.Account = account
	}
	if f.CurrencyKey != "" {
		currency := getString(row, f.CurrencyKey)
		allowed := false
		for _, id := range cfg.RUBCurrencyIDs {
			allowed = allowed || currency == id
		}
		if !allowed {
			return contracts.PlannedEvent{}, "unsupported_currency"
		}
	}
	if f.DueDate != "" && getString(row, f.DueDate) != "" {
		due, err := parseDate(getString(row, f.DueDate))
		if err != nil {
			return contracts.PlannedEvent{}, "invalid_due_date"
		}
		event.DueDate = &due
		event.Date = due
		event.DateQuality = "source"
	}
	if getString(row, f.Deleted) == "true" {
		event.PaidKopecks = paid
		if linked {
			event.LinkStatus = "reconciled"
		}
		if paid > total {
			event.LinkStatus = "overpaid"
		}
		event.Status, event.RemainingKopecks, event.AmountKopecks = "cancelled", 0, 0
		return event, ""
	}
	if !linked {
		return event, ""
	}
	event.LinkStatus = "reconciled"
	if paid > total {
		event.Status, event.LinkStatus = "needs_reconciliation", "overpaid"
		event.PaidKopecks, event.RemainingKopecks, event.AmountKopecks = paid, 0, 0
		return event, ""
	}
	event.PaidKopecks = paid
	event.RemainingKopecks = total - paid
	event.AmountKopecks = event.RemainingKopecks
	switch {
	case paid == total:
		event.Status = "paid"
	case paid > 0:
		event.Status = "partially_paid"
	case event.DueDate != nil && *event.DueDate < now.Format("2006-01-02"):
		event.Status = "overdue"
	}
	event.ForecastEligible = event.DueDate != nil && event.RemainingKopecks > 0
	return event, ""
}
