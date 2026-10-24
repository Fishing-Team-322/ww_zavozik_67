package onecodata

import (
	"context"
	"net/http"
	"strings"
	"time"
)

// SuggestAccounting builds a mapping for the published standard OData objects
// of 1C Accounting 3.0. The caller supplies the company's INN and one of its
// bank account numbers; internal 1C references are discovered, not guessed.
func (c Client) SuggestAccounting(ctx context.Context, root, companyID, inn, account string) (Config, *PlanConfig, error) {
	if len(account) != 20 || !digits(account) || inn == "" {
		return Config{}, nil, ErrConfig
	}
	discovery, err := c.Inspect(ctx, root)
	if err != nil {
		return Config{}, nil, err
	}
	fields := make(map[string]map[string]bool, len(discovery.Collections))
	for _, collection := range discovery.Collections {
		available := make(map[string]bool, len(collection.Fields))
		for _, field := range collection.Fields {
			available[field.Name] = true
		}
		fields[collection.Name] = available
	}
	has := func(entity string, names ...string) bool {
		available := fields[entity]
		if available == nil {
			return false
		}
		for _, name := range names {
			if !available[name] {
				return false
			}
		}
		return true
	}
	if !has("Catalog_Организации", "Ref_Key", "ИНН") ||
		!has("Catalog_БанковскиеСчета", "Ref_Key", "Owner", "Owner_Type", "НомерСчета") {
		return Config{}, nil, ErrConfig
	}
	if !has("Document_ПоступлениеНаРасчетныйСчет", "Ref_Key", "Number", "Date", "СуммаДокумента", "Posted", "СчетОрганизации_Key") &&
		!has("Document_СписаниеСРасчетногоСчета", "Ref_Key", "Number", "Date", "СуммаДокумента", "Posted", "СчетОрганизации_Key") {
		return Config{}, nil, ErrConfig
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
	orgs, err := c.planRows(ctx, client, root, "Catalog_Организации")
	if err != nil {
		return Config{}, nil, err
	}
	organization := ""
	for _, row := range orgs {
		if getString(row, "ИНН") == inn {
			if organization != "" {
				return Config{}, nil, ErrConfig
			}
			organization = getString(row, "Ref_Key")
		}
	}
	if organization == "" {
		return Config{}, nil, ErrConfig
	}
	accounts, err := c.planRows(ctx, client, root, "Catalog_БанковскиеСчета")
	if err != nil {
		return Config{}, nil, err
	}
	accountMap := map[string]string{}
	selected := false
	for _, row := range accounts {
		if getString(row, "Owner") != organization || !strings.HasSuffix(getString(row, "Owner_Type"), "Catalog_Организации") {
			continue
		}
		number, key := getString(row, "НомерСчета"), getString(row, "Ref_Key")
		if len(number) != 20 || !digits(number) || key == "" {
			continue
		}
		accountMap[key] = number
		selected = selected || number == account
	}
	if !selected {
		return Config{}, nil, ErrConfig
	}
	config := Config{BaseURL: root, CompanyID: companyID, CompanyINN: inn, CompanyAccount: account, AccountMap: accountMap}
	if has("Catalog_Контрагенты", "Ref_Key", "ИНН", "Description") {
		config.Counterparties = &ReferenceCatalog{EntitySet: "Catalog_Контрагенты", Key: "Ref_Key", INN: "ИНН", Name: "Description"}
	}
	for _, spec := range []struct{ entity, direction string }{
		{"Document_ПоступлениеНаРасчетныйСчет", "in"},
		{"Document_СписаниеСРасчетногоСчета", "out"},
	} {
		if !has(spec.entity, "Ref_Key", "Number", "Date", "СуммаДокумента", "Posted", "СчетОрганизации_Key") {
			continue
		}
		f := FieldMap{ExternalID: "Ref_Key", Number: "Number", DocumentDate: "Date", ExecutionDate: "Date", Amount: "СуммаДокумента", Posted: "Posted", AccountKey: "СчетОрганизации_Key"}
		if has(spec.entity, "Контрагент") {
			f.CounterpartyKey = "Контрагент"
		}
		if has(spec.entity, "НазначениеПлатежа") {
			f.Purpose = "НазначениеПлатежа"
		}
		if has(spec.entity, "НеПодтвержденоВыпискойБанка") {
			f.Unconfirmed = "НеПодтвержденоВыпискойБанка"
		}
		config.Collections = append(config.Collections, Collection{EntitySet: spec.entity, Direction: spec.direction, Fields: f})
	}
	if config.Validate() != nil {
		return Config{}, nil, ErrConfig
	}
	if !has("Catalog_Валюты", "Ref_Key", "Code") {
		return config, nil, nil
	}
	plan := &PlanConfig{BaseURL: root, CompanyID: companyID, DataMode: "live", OrganizationIDs: []string{organization}, AccountMap: accountMap}
	for _, spec := range []struct{ entity, direction string }{
		{"Document_СчетНаОплатуПокупателю", "in"},
		{"Document_СчетНаОплатуПоставщика", "out"},
	} {
		if !has(spec.entity, "Ref_Key", "Number", "Date", "СуммаДокумента", "Posted", "DeletionMark", "Организация_Key", "ВалютаДокумента_Key") {
			continue
		}
		f := InvoiceFields{ExternalID: "Ref_Key", Number: "Number", DocumentDate: "Date", Amount: "СуммаДокумента", Posted: "Posted", Deleted: "DeletionMark", OrganizationKey: "Организация_Key", CurrencyKey: "ВалютаДокумента_Key"}
		if has(spec.entity, "DataVersion") {
			f.SourceVersion = "DataVersion"
		}
		plan.Invoices = append(plan.Invoices, InvoiceSource{EntitySet: spec.entity, Direction: spec.direction, Fields: f})
	}
	if len(plan.Invoices) == 0 {
		return config, nil, nil
	}
	currencies, err := c.planRows(ctx, client, root, "Catalog_Валюты")
	if err != nil {
		return Config{}, nil, err
	}
	for _, row := range currencies {
		if code := strings.TrimSpace(getString(row, "Code")); code == "643" || strings.EqualFold(code, "RUB") {
			plan.RUBCurrencyIDs = append(plan.RUBCurrencyIDs, getString(row, "Ref_Key"))
		}
	}
	if len(plan.RUBCurrencyIDs) == 0 {
		return Config{}, nil, ErrConfig
	}
	for _, invoice := range plan.Invoices {
		var detail, parent string
		if invoice.Direction == "in" {
			detail, parent = "Document_ПоступлениеНаРасчетныйСчет_РасшифровкаПлатежа", "Document_ПоступлениеНаРасчетныйСчет"
		} else {
			detail, parent = "Document_СписаниеСРасчетногоСчета_РасшифровкаПлатежа", "Document_СписаниеСРасчетногоСчета"
		}
		if !has(detail, "Ref_Key", "LineNumber", "СчетНаОплату_Key", "СуммаПлатежа") || !has(parent, "Ref_Key", "Posted", "Организация_Key") {
			continue
		}
		p := PaymentSource{EntitySet: detail, InvoiceEntitySet: invoice.EntitySet, Fields: PaymentFields{ExternalID: "Ref_Key", LineNumber: "LineNumber", InvoiceKey: "СчетНаОплату_Key", Amount: "СуммаПлатежа"}, Parent: &PaymentParent{EntitySet: parent, ExternalID: "Ref_Key", Posted: "Posted", OrganizationKey: "Организация_Key"}}
		if has(parent, "НеПодтвержденоВыпискойБанка") {
			p.Parent.Unconfirmed = "НеПодтвержденоВыпискойБанка"
		}
		plan.Payments = append(plan.Payments, p)
	}
	if plan.Validate() != nil {
		return Config{}, nil, ErrConfig
	}
	return config, plan, nil
}
