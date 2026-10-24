package product

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"math"
	"net/http"
	"sort"
	"strconv"
	"time"
	"unicode/utf8"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/google/uuid"
)

const usnSource = "https://www.nalog.gov.ru/rn61/taxation/taxes/usn/"
const vatSource = "https://www.nalog.gov.ru/rn77/taxation/taxes/nds/"
const enpSource = "https://www.nalog.gov.ru/rn33/ens/"

// Tax scheduling uses a confirmed liability, never treats all bank credits as a tax base.
// ENP is a payment method: a manual ENP plan must not duplicate the same USN/VAT liability.
func taxDates(kind, period, legalForm, explicit string, year int) ([]time.Time, string, error) {
	var dates []time.Time
	source := usnSource
	dt := func(y, m, d int) time.Time { return time.Date(y, time.Month(m), d, 0, 0, 0, 0, time.UTC) }
	switch kind {
	case "usn_advance":
		month := map[string]int{"q1": 4, "h1": 7, "9m": 10}[period]
		if month == 0 {
			return nil, "", bad("Для аванса УСН выберите q1, h1 или 9m")
		}
		dates = []time.Time{dt(year, month, 28)}
	case "usn_annual":
		if period != "year" {
			return nil, "", bad("Годовой УСН: period=year")
		}
		month := 3
		if legalForm == "ИП" {
			month = 4
		}
		dates = []time.Time{dt(year+1, month, 28)}
	case "vat":
		quarter := map[string]int{"q1": 1, "q2": 2, "q3": 3, "q4": 4}[period]
		if quarter == 0 {
			return nil, "", bad("Для НДС выберите квартал q1–q4")
		}
		for i := 1; i <= 3; i++ {
			dates = append(dates, dt(year, quarter*3+i, 28))
		}
		source = vatSource
	case "enp", "contributions", "other":
		d, e := day(explicit)
		if e != nil {
			return nil, "", e
		}
		if d.Year() != year {
			return nil, "", bad("Год ручного срока должен совпадать с year")
		}
		return []time.Time{d}, enpSource, nil
	default:
		return nil, "", bad("Неизвестный вид налогового обязательства")
	}
	if explicit != "" {
		return nil, "", bad("Для УСН и НДС срок рассчитывает календарь; для индивидуального срока используйте other")
	}
	for i, d := range dates {
		if nonWorkdays[d.Year()] == nil {
			return nil, "", platform.Fail(422, "tax_calendar_unavailable", "Для года срока нет производственного календаря. Укажите подтверждённый индивидуальный срок через other")
		}
		for !isWorkday(d) {
			d = d.AddDate(0, 0, 1)
		}
		dates[i] = d
	}
	return dates, source, nil
}

func taxDraft(company platform.Company, b Doc, confirmed bool) (Doc, error) {
	if e := fields(b, "request_id kind period year amount title due_date source_ref confirmed additional"); e != nil {
		return nil, e
	}
	if confirmed && !flag(b, "confirmed") {
		return nil, bad("Подтвердите сумму налогового обязательства")
	}
	if _, ok := b["additional"].(bool); !ok {
		return nil, bad("Укажите additional: является ли обязательство дополнительным к обычному потоку")
	}
	if _, ok := b["confirmed"].(bool); !ok {
		return nil, bad("Укажите confirmed")
	}
	y, ok := b["year"].(float64)
	if !ok || y != math.Trunc(y) || y < 2024 || y > 2100 {
		return nil, bad("Некорректный год обязательства")
	}
	amount, ok := b["amount"].(float64)
	if !ok || math.IsNaN(amount) || math.IsInf(amount, 0) || amount <= 0 || amount > 1e13 || math.Abs(amount*100-math.Round(amount*100)) > .001 {
		return nil, bad("Сумма должна быть положительной, с точностью до копейки")
	}
	for _, key := range []string{"kind", "period", "title", "source_ref"} {
		v, ok := b[key].(string)
		if !ok || v == "" || utf8.RuneCountInString(v) > 500 {
			return nil, bad("Заполните поле: " + key)
		}
	}
	dates, source, e := taxDates(text(b, "kind"), text(b, "period"), company.LegalForm, text(b, "due_date"), int(y))
	if e != nil {
		return nil, e
	}
	// Split in integer kopecks so the installment sum equals the confirmed total.
	cents := int64(math.Round(amount * 100))
	if cents < int64(len(dates)) {
		return nil, bad("Сумма меньше числа частей платежа в копейках")
	}
	payments := []Doc{}
	for i, d := range dates {
		part := cents / int64(len(dates))
		if int64(i) < cents%int64(len(dates)) {
			part++
		}
		payments = append(payments, Doc{"date": d.Format(domain.DateLayout), "amount": float64(part) / 100, "status": "expected"})
	}
	rule := "statutory_calendar"
	if in(text(b, "kind"), "enp contributions other") {
		rule = "manual_confirmed"
	}
	return Doc{"kind": b["kind"], "period": b["period"], "year": y, "amount": amount, "title": b["title"], "source_ref": b["source_ref"], "source_url": source, "confirmed": flag(b, "confirmed"), "additional": b["additional"], "payments": payments, "status": "active", "calculation_basis": "confirmed_liability", "date_rule": rule}, nil
}

func taxView(d Doc, events []Doc) Doc {
	out := view("tax", d)
	delete(out, "input_hash")
	payments := []Doc{}
	paid := 0.0
	for i, p := range docs(d["payments"]) {
		v := Doc{"date": p["date"], "amount": p["amount"], "status": "expected", "event_id": idFor(text(d, "company_id"), "tax:"+text(d, "id")+":"+strconv.Itoa(i))}
		for _, event := range events {
			if text(event, "id") == v["event_id"] {
				v["status"] = event["status"]
				break
			}
		}
		if text(v, "status") == "received" {
			paid += number(v, "amount")
		}
		payments = append(payments, v)
	}
	out["payments"], out["paid_amount"] = payments, money(paid)
	return out
}

func (s *Service) taxAction(ctx context.Context, op, uid, cid string, r *http.Request, b Doc) (Result, error) {
	if op == "cancelTax" {
		d, e := s.DB.ProductGet(ctx, uid, "tax", r.PathValue("taxId"))
		if e != nil {
			return Result{}, e
		}
		if text(d, "status") == "cancelled" {
			return Result{Status: 204}, nil
		}
		d["status"] = "cancelled"
		if _, e = s.DB.ProductSave(ctx, uid, text(d, "company_id"), "tax", text(d, "id"), d, false); e != nil {
			return Result{}, e
		}
		return Result{Status: 204}, nil
	}
	company, e := s.DB.GetCompany(ctx, uid, cid)
	if e != nil {
		return Result{}, e
	}
	d, e := taxDraft(company, b, op == "createTax")
	if e != nil {
		return Result{}, e
	}
	if op == "previewTax" {
		return ok(d)
	}
	requestID, e := uuid.Parse(text(b, "request_id"))
	if e != nil || requestID == uuid.Nil {
		return Result{}, bad("request_id должен быть UUID для повторной отправки того же обязательства")
	}
	id := idFor(cid, "tax-request:"+requestID.String())
	hash := sha256.Sum256(store.JSON(d))
	d["input_hash"] = hex.EncodeToString(hash[:])
	d["id"], d["company_id"] = id, cid
	saved, e := s.DB.ProductSave(ctx, uid, cid, "tax", id, d, true)
	if e != nil {
		return Result{}, e
	}
	if saved["input_hash"] != d["input_hash"] {
		return Result{}, platform.Fail(409, "request_conflict", "Этот request_id уже использован с другой суммой или параметрами")
	}
	events, e := s.DB.ProductList(ctx, uid, cid, "event")
	if e != nil {
		return Result{}, e
	}
	return Result{Status: 201, Body: taxView(saved, events)}, nil
}

func (s *Service) taxes(ctx context.Context, uid, cid string, r *http.Request) (Result, error) {
	company, e := s.DB.GetCompany(ctx, uid, cid)
	if e != nil {
		return Result{}, e
	}
	year := today().Year()
	if raw := r.URL.Query().Get("year"); raw != "" {
		year, e = strconv.Atoi(raw)
		if e != nil || year < 2024 || year > 2100 {
			return Result{}, bad("Некорректный year")
		}
	}
	months := 3
	if raw := r.URL.Query().Get("months"); raw != "" {
		months, e = strconv.Atoi(raw)
		if e != nil || months < 1 || months > 12 {
			return Result{}, bad("months должен быть от 1 до 12")
		}
	}
	calendar := []Doc{}
	for _, rule := range [][2]string{{"usn_advance", "q1"}, {"usn_advance", "h1"}, {"usn_advance", "9m"}, {"usn_annual", "year"}, {"vat", "q1"}, {"vat", "q2"}, {"vat", "q3"}, {"vat", "q4"}} {
		dates, source, err := taxDates(rule[0], rule[1], company.LegalForm, "", year)
		if err != nil {
			continue
		}
		values := []string{}
		for _, d := range dates {
			values = append(values, d.Format(domain.DateLayout))
		}
		calendar = append(calendar, Doc{"kind": rule[0], "period": rule[1], "year": year, "dates": values, "source_url": source})
	}
	events, e := s.DB.ProductList(ctx, uid, cid, "event")
	if e != nil {
		return Result{}, e
	}
	rows, e := s.DB.ProductList(ctx, uid, cid, "tax")
	if e != nil {
		return Result{}, e
	}
	obligations := []Doc{}
	items := []Doc{}
	until := today().AddDate(0, months, 0).Format(domain.DateLayout)
	for _, d := range rows {
		v := taxView(d, events)
		obligations = append(obligations, v)
		for _, p := range docs(v["payments"]) {
			if text(p, "status") == "expected" && text(p, "date") >= today().Format(domain.DateLayout) && text(p, "date") < until {
				items = append(items, Doc{"date": p["date"], "title": d["title"], "amount_estimate": p["amount"], "how_calculated": "Подтверждённая сумма обязательства", "event_id": p["event_id"]})
			}
		}
	}
	sort.Slice(obligations, func(i, j int) bool { return text(obligations[i], "created_at") > text(obligations[j], "created_at") })
	return ok(Doc{"tax_regime": company.TaxRegime, "regime_detected": nil, "items": items, "calendar": calendar, "obligations": obligations, "year": year, "calculation_basis": "confirmed_liabilities", "notice": "Сроки общего порядка. Индивидуальные отсрочки и суммы подтвердите по учётной системе. ЕНП не добавляется повторно поверх того же обязательства."})
}
