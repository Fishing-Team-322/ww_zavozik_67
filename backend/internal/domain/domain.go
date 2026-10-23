// Package domain — общий язык всех пакетов бэкенда. Меняем только
// договорившись: от этих типов зависят все.
package domain

import "time"

type Direction string

const (
	In  Direction = "in"
	Out Direction = "out"
)

// Category совпадает с enum Category в api/openapi.yaml.
type Category string

const (
	CatRevenueAcquiring   Category = "revenue_acquiring"
	CatRevenueSBP         Category = "revenue_sbp"
	CatRevenueCash        Category = "revenue_cash"
	CatRevenueB2B         Category = "revenue_b2b"
	CatRevenueMarketplace Category = "revenue_marketplace"
	CatSupplier           Category = "supplier"
	CatSalary             Category = "salary"
	CatTax                Category = "tax"
	CatRent               Category = "rent"
	CatUtilities          Category = "utilities"
	CatLoanPayment        Category = "loan_payment"
	CatLeasing            Category = "leasing"
	CatBankFee            Category = "bank_fee"
	CatMarketing          Category = "marketing"
	CatServices           Category = "services"
	CatOwnTransfer        Category = "own_transfer"
	CatOwnerLoan          Category = "owner_loan"
	CatRefund             Category = "refund"
	CatEnforcement        Category = "enforcement"
	CatOther              Category = "other"
	CatUnknown            Category = ""
)

// IsInternal — движение денег владельца, а не бизнеса: не выручка и не расход,
// в прогноз как поток не идёт, зато сигналит о разрыве в прошлом.
func (c Category) IsInternal() bool {
	return c == CatOwnTransfer || c == CatOwnerLoan
}

// SourceKind совпадает с enum SourceKind в api/openapi.yaml.
type SourceKind string

const (
	SrcUpload       SourceKind = "upload"
	SrcOneCBankFile SourceKind = "onec_bank_file"
	SrcExcel        SourceKind = "excel"
	SrcGSheets      SourceKind = "gsheets"
	SrcOneCOData    SourceKind = "onec_odata"
	SrcFNS          SourceKind = "fns"
	SrcManual       SourceKind = "manual"
)

type CategoryMethod string

const (
	MethodRule CategoryMethod = "rule"
	MethodML   CategoryMethod = "ml"
	MethodLLM  CategoryMethod = "llm"
	MethodUser CategoryMethod = "user"
)

type TaxRegime string

const (
	TaxUSN6    TaxRegime = "usn6"
	TaxUSN15   TaxRegime = "usn15"
	TaxOSNO    TaxRegime = "osno"
	TaxESHN    TaxRegime = "eshn"
	TaxUnknown TaxRegime = "unknown"
)

type Company struct {
	ID        string
	Name      string
	INN       INN
	LegalForm string
	Industry  string
	TaxRegime TaxRegime
	Reserve   Money // неснижаемый остаток, ниже которого считаем разрывом
}

// Operation — фактическая операция по счёту. Date — полночь UTC.
type Operation struct {
	ID               string
	CompanyID        string
	Date             time.Time
	Amount           Money // всегда >= 0, знак задаёт Direction
	Direction        Direction
	CounterpartyINN  INN
	CounterpartyName Name
	Purpose          Purpose
	BalanceEOD       *Money // остаток на конец дня, если источник его даёт
	Category         Category
	CategoryMethod   CategoryMethod
	Source           SourceKind
	DedupHash        string
}

// Signed — сумма со знаком: поступление +, списание −.
func (o Operation) Signed() Money {
	if o.Direction == Out {
		return -o.Amount
	}
	return o.Amount
}

type EventStatus string

const (
	EventExpected  EventStatus = "expected"
	EventReceived  EventStatus = "received"
	EventMissed    EventStatus = "missed"
	EventCancelled EventStatus = "cancelled"
)

// PlannedEvent — ожидаемое движение денег, которого ещё нет в выписке:
// счёт, договор, налог, ручной ввод.
type PlannedEvent struct {
	ID               string
	CompanyID        string
	Date             time.Time
	Amount           Money
	Direction        Direction
	Title            string
	Category         Category
	CounterpartyName Name
	Probability      float64 // 0..1
	Source           SourceKind
	Status           EventStatus
}

type Period string

const (
	Weekly    Period = "weekly"
	Biweekly  Period = "biweekly"
	Monthly   Period = "monthly"
	Quarterly Period = "quarterly"
)

// RecurringPattern — найденный регулярный платёж или поступление.
type RecurringPattern struct {
	ID               string
	CompanyID        string
	Title            string
	Category         Category
	Direction        Direction
	CounterpartyINN  INN
	CounterpartyName Name
	Period           Period
	DayOfMonth       int
	Amount           Money
	AmountSpread     Money
	NextDate         time.Time
	Confirmed        bool
}

// DailyFlow — потоки за календарный день. Missing — день внутри пропуска
// в выписке: значения не настоящие, модели их пропускают.
type DailyFlow struct {
	Date    time.Time
	Inflow  Money
	Outflow Money
	Balance *Money
	Missing bool
}

// Day — дата без времени (полночь UTC), единый формат дат в домене.
func Day(t time.Time) time.Time {
	y, m, d := t.Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

const DateLayout = "2006-01-02"
