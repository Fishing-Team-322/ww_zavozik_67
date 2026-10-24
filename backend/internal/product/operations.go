package product

import (
	"context"
	"encoding/base64"
	"math"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/xuri/excelize/v2"
)

func Categories() []Doc {
	labels := []string{"Выручка по картам", "Выручка СБП", "Наличная выручка", "Оплата от компаний", "Маркетплейсы", "Поставщики", "Зарплата", "Налоги", "Аренда", "Коммунальные услуги", "Кредиты", "Лизинг", "Комиссии банка", "Реклама", "Услуги", "Переводы между своими счетами", "Средства владельца", "Возвраты", "Взыскания", "Прочее"}
	out := []Doc{}
	for i, c := range domain.AllCategories {
		group := "expense"
		if strings.HasPrefix(string(c), "revenue_") {
			group = "income"
		}
		if c.IsInternal() {
			group = "internal"
		}
		out = append(out, Doc{"key": string(c), "title": labels[i], "group": group, "icon": "wallet"})
	}
	return out
}
func (s *Service) operationRows(ctx context.Context, uid, cid string, r *http.Request) ([]Doc, error) {
	rows, e := s.DB.ProductList(ctx, uid, cid, "operation")
	if e != nil {
		return nil, e
	}
	from, to, e := rangeDates(r)
	if e != nil {
		return nil, e
	}
	rows = filterDates(rows, from, to, "op_date")
	q := r.URL.Query()
	out := []Doc{}
	for _, d := range rows {
		if flag(d, "is_duplicate") {
			continue
		}
		if v := q.Get("direction"); v != "" && text(d, "direction") != v {
			continue
		}
		if v := q.Get("category"); v != "" && text(d, "category") != v {
			continue
		}
		if v := q.Get("source"); v != "" && text(d, "source") != v {
			continue
		}
		if v := q.Get("counterparty_id"); v != "" && cpRef(cid, d)["id"] != v {
			continue
		}
		if v := strings.ToLower(q.Get("q")); v != "" && !strings.Contains(strings.ToLower(text(d, "purpose")+" "+text(d, "counterparty_name")), v) {
			continue
		}
		out = append(out, d)
	}
	return out, nil
}

// Operation cursors include the date so pagination keeps newest transactions first.
func pageOperations(rows []Doc, r *http.Request) (Doc, error) {
	limit := 100
	if raw := r.URL.Query().Get("limit"); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil || n < 1 || n > 1000 {
			return nil, bad("limit должен быть от 1 до 1000")
		}
		limit = n
	}
	key := func(row Doc) string { return text(row, "date") + "|" + text(row, "id") }
	sort.Slice(rows, func(i, j int) bool { return key(rows[i]) > key(rows[j]) })
	start := 0
	if cursor := r.URL.Query().Get("cursor"); cursor != "" {
		decoded, err := base64.RawURLEncoding.DecodeString(cursor)
		if err != nil || len(decoded) > 256 {
			return nil, bad("Некорректный cursor")
		}
		for start < len(rows) && key(rows[start]) != string(decoded) {
			start++
		}
		if start == len(rows) {
			return nil, bad("Некорректный cursor")
		}
		start++
	}
	end := start + limit
	if end > len(rows) {
		end = len(rows)
	}
	var next any
	if end < len(rows) {
		next = base64.RawURLEncoding.EncodeToString([]byte(key(rows[end-1])))
	}
	return Doc{"items": rows[start:end], "next_cursor": next, "total": len(rows)}, nil
}

func (s *Service) operations(ctx context.Context, op, uid, cid string, r *http.Request, b Doc) (Result, error) {
	rows, e := s.operationRows(ctx, uid, cid, r)
	if e != nil {
		return Result{}, e
	}
	switch op {
	case "listOperations":
		out := []Doc{}
		for _, d := range rows {
			out = append(out, view("operation", d))
		}
		p, e := pageOperations(out, r)
		return Result{Status: 200, Body: p}, e
	case "summarizeOperations":
		totalIn, totalOut, internal := float64(0), float64(0), float64(0)
		groups := map[string]Doc{}
		for _, d := range rows {
			amount := number(d, "amount")
			if flag(d, "is_internal") {
				internal += amount
				continue
			}
			key := text(d, "category")
			g := groups[key]
			if g == nil {
				g = Doc{"category": key, "in": float64(0), "out": float64(0), "count": float64(0)}
				groups[key] = g
			}
			direction := text(d, "direction")
			g[direction] = number(g, direction) + amount
			g["count"] = number(g, "count") + 1
			if direction == "in" {
				totalIn += amount
			} else {
				totalOut += amount
			}
		}
		cats := []Doc{}
		for _, g := range groups {
			g["in"] = money(number(g, "in"))
			g["out"] = money(number(g, "out"))
			cats = append(cats, g)
		}
		sort.Slice(cats, func(i, j int) bool { return text(cats[i], "category") < text(cats[j], "category") })
		return ok(Doc{"total_in": money(totalIn), "total_out": money(totalOut), "net": money(totalIn - totalOut), "by_category": cats, "internal_total": money(internal)})
	case "exportOperations":
		if f := r.URL.Query().Get("format"); f != "" && f != "xlsx" {
			return Result{}, bad("Поддерживается format=xlsx")
		}
		file := excelize.NewFile()
		defer file.Close()
		headers := []string{"Дата", "Сумма, ₽", "Направление", "Контрагент", "Назначение", "Категория", "Внутренний перевод"}
		for i, h := range headers {
			cell, _ := excelize.CoordinatesToCellName(i+1, 1)
			file.SetCellStr("Sheet1", cell, h)
		}
		for n, d := range rows {
			values := []any{date(d["op_date"]), number(d, "amount"), text(d, "direction"), text(d, "counterparty_name"), text(d, "purpose"), text(d, "category"), flag(d, "is_internal")}
			for i, v := range values {
				cell, _ := excelize.CoordinatesToCellName(i+1, n+2)
				if str, ok := v.(string); ok {
					file.SetCellStr("Sheet1", cell, str)
				} else {
					file.SetCellValue("Sheet1", cell, v)
				}
			}
		}
		buf, e := file.WriteToBuffer()
		if e != nil {
			return Result{}, e
		}
		return Result{Status: 200, Data: buf.Bytes(), MIME: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", Filename: "operations.xlsx"}, nil
	case "recategorizeOperations":
		if e := fields(b, "counterparty_id category apply_to"); e != nil {
			return Result{}, e
		}
		category, cp, apply := text(b, "category"), text(b, "counterparty_id"), text(b, "apply_to")
		if !knownCategory(category) || cp == "" || !in(apply, "all future") {
			return Result{}, bad("Нужны counterparty_id, category и apply_to: all/future")
		}
		key := ""
		changed := 0
		for _, d := range rows {
			if cpRef(cid, d)["id"] == cp {
				key = cpKey(d)
				if apply == "all" {
					d["category"] = category
					d["is_internal"] = domain.Category(category).IsInternal()
					if _, e = s.DB.ProductSave(ctx, uid, cid, "operation", text(d, "id"), d, false); e != nil {
						return Result{}, e
					}
					changed++
				}
			}
		}
		if key == "" {
			return Result{}, platform.ErrNotFound
		}
		_, e = s.DB.Pool.Exec(ctx, "INSERT INTO category_rules(company_id,counterparty_key,category) VALUES($1,$2,$3) ON CONFLICT(company_id,counterparty_key) DO UPDATE SET category=EXCLUDED.category", cid, key, category)
		if e != nil {
			return Result{}, e
		}
		return ok(Doc{"changed": changed})
	}
	return Result{}, bad("Неизвестная операция")
}
func (s *Service) counterparties(ctx context.Context, op, uid, cid string, r *http.Request) (Result, error) {
	rows, e := s.DB.ProductList(ctx, uid, cid, "operation")
	if e != nil {
		return Result{}, e
	}
	invoices, e := s.DB.ProductList(ctx, uid, cid, "invoice")
	if e != nil {
		return Result{}, e
	}
	groups := map[string]Doc{}
	revenue := float64(0)
	cutoff := today().AddDate(-1, 0, 0).Format(domain.DateLayout)
	for _, d := range rows {
		if flag(d, "is_duplicate") {
			continue
		}
		ref := cpRef(cid, d)
		id, _ := ref["id"].(string)
		if id == "" {
			continue
		}
		g := groups[id]
		if g == nil {
			var inn any
			if v := text(d, "counterparty_inn"); v != "" {
				inn = v
			}
			g = Doc{"id": id, "name": ref["name"], "inn": inn, "roles": []string{}, "turnover_in_12m": float64(0), "turnover_out_12m": float64(0), "revenue_share": float64(0), "operations_count": 0, "first_at": date(d["op_date"]), "last_at": date(d["op_date"]), "avg_payment_delay_days": nil, "delay_stability": nil, "discipline_score": nil, "overdue_amount": float64(0), "fns_status": nil}
			groups[id] = g
		}
		g["operations_count"] = int(number(g, "operations_count")) + 1
		dt := date(d["op_date"])
		if dt < text(g, "first_at") {
			g["first_at"] = dt
		}
		if dt > text(g, "last_at") {
			g["last_at"] = dt
		}
		if dt >= cutoff && !flag(d, "is_internal") {
			key := "turnover_" + text(d, "direction") + "_12m"
			g[key] = number(g, key) + number(d, "amount")
			if text(d, "direction") == "in" {
				revenue += number(d, "amount")
			}
		}
	}
	delays := map[string][]float64{}
	for _, d := range invoices {
		ref := cpRef(cid, d)
		id, _ := ref["id"].(string)
		g := groups[id]
		if g == nil {
			if id == "" {
				continue
			}
			g = Doc{"id": id, "name": ref["name"], "inn": d["counterparty_inn"], "roles": []string{}, "turnover_in_12m": float64(0), "turnover_out_12m": float64(0), "revenue_share": float64(0), "operations_count": 0, "first_at": d["issued_at"], "last_at": d["issued_at"], "avg_payment_delay_days": nil, "delay_stability": nil, "discipline_score": nil, "overdue_amount": float64(0), "fns_status": nil}
			groups[id] = g
		}
		if text(d, "direction") == "issued" && text(d, "status") == "paid" && text(d, "paid_at") != "" {
			paid, pe := day(date(d["paid_at"]))
			due, de := day(date(d["due_at"]))
			if pe == nil && de == nil {
				delays[id] = append(delays[id], paid.Sub(due).Hours()/24)
			}
		}
		if text(d, "due_at") < today().Format(domain.DateLayout) && number(d, "amount") > number(d, "paid_amount") {
			g["overdue_amount"] = number(g, "overdue_amount") + number(d, "amount") - number(d, "paid_amount")
		}
	}
	registry, e := s.DB.ProductList(ctx, uid, cid, "registry")
	if e != nil {
		return Result{}, e
	}
	for _, record := range registry {
		if text(record, "target") != "counterparty" {
			continue
		}
		ref := cpRef(cid, Doc{"counterparty_inn": record["inn"], "counterparty_name": record["name"]})
		id := ref["id"].(string)
		g := groups[id]
		if g == nil {
			g = Doc{"id": id, "name": record["name"], "inn": record["inn"], "roles": []string{}, "turnover_in_12m": float64(0), "turnover_out_12m": float64(0), "revenue_share": float64(0), "operations_count": 0, "first_at": nil, "last_at": nil, "avg_payment_delay_days": nil, "delay_stability": nil, "discipline_score": nil, "overdue_amount": float64(0)}
			groups[id] = g
		}
		old, _ := g["registry"].(Doc)
		if old == nil || text(record, "actual_at") > text(old, "actual_at") || text(record, "actual_at") == text(old, "actual_at") && text(record, "created_at") > text(old, "created_at") {
			g["registry"] = record
			g["fns_status"] = text(record, "registration_status") + " · сведения на " + text(record, "actual_at")
		}
	}
	out := []Doc{}
	for _, g := range groups {
		if values := delays[text(g, "id")]; len(values) > 0 {
			sum, onTime := float64(0), 0
			for _, v := range values {
				sum += v
				if v <= 0 {
					onTime++
				}
			}
			mean := sum / float64(len(values))
			variance := float64(0)
			for _, v := range values {
				variance += (v - mean) * (v - mean)
			}
			g["avg_payment_delay_days"] = money(mean)
			g["delay_stability"] = money(math.Sqrt(variance / float64(len(values))))
			g["discipline_score"] = money(100 * float64(onTime) / float64(len(values)))
			g["payment_samples"] = len(values)
			g["discipline_basis"] = "percent_of_matched_issued_invoices_paid_by_due_date"
		}
		roles := []string{}
		if number(g, "turnover_in_12m") > 0 {
			roles = append(roles, "client")
		}
		if number(g, "turnover_out_12m") > 0 {
			roles = append(roles, "supplier")
		}
		g["roles"] = roles
		if revenue > 0 {
			g["revenue_share"] = number(g, "turnover_in_12m") / revenue
		}
		out = append(out, g)
	}
	sort.Slice(out, func(i, j int) bool { return number(out[i], "turnover_in_12m") > number(out[j], "turnover_in_12m") })
	if op == "getConcentration" {
		top := []Doc{}
		first, three := float64(0), float64(0)
		for i, g := range out {
			share := number(g, "revenue_share")
			if i == 0 {
				first = share
			}
			if i < 3 {
				three += share
			}
			if i < 10 {
				top = append(top, Doc{"counterparty_id": g["id"], "share": share})
			}
		}
		msg := "Данных о выручке пока нет"
		if revenue > 0 {
			msg = "Выручка распределена между клиентами"
			if first > 0.5 {
				msg = "Больше половины выручки зависит от одного клиента"
			}
		}
		return ok(Doc{"top_client_share": first, "top3_share": three, "risk_text": msg, "top": top})
	}
	if op == "getCounterparty" {
		id := r.PathValue("cpId")
		g := groups[id]
		if g == nil {
			return Result{}, platform.ErrNotFound
		}
		monthly := map[string]Doc{}
		for _, d := range rows {
			if cpRef(cid, d)["id"] != id {
				continue
			}
			m := date(d["op_date"])[:7]
			if monthly[m] == nil {
				monthly[m] = Doc{"month": m, "in": float64(0), "out": float64(0)}
			}
			direction := text(d, "direction")
			monthly[m][direction] = number(monthly[m], direction) + number(d, "amount")
		}
		months := []Doc{}
		for _, v := range monthly {
			months = append(months, v)
		}
		sort.Slice(months, func(i, j int) bool { return text(months[i], "month") < text(months[j], "month") })
		matching := []Doc{}
		open := []Doc{}
		for _, d := range invoices {
			if cpRef(cid, d)["id"] == id {
				matching = append(matching, view("invoice", d))
				if text(d, "status") != "paid" {
					open = append(open, view("invoice", d))
				}
			}
		}
		g["monthly"] = months
		g["invoices"] = matching
		g["open_invoices"] = open
		g["next_payment_expected"] = nil
		for _, invoice := range open {
			if text(invoice, "direction") == "issued" && text(invoice, "expected_pay_at") >= today().Format(domain.DateLayout) {
				next, _ := g["next_payment_expected"].(Doc)
				if next == nil || text(invoice, "expected_pay_at") < text(next, "date") {
					g["next_payment_expected"] = Doc{"date": invoice["expected_pay_at"], "amount": money(number(invoice, "amount") - number(invoice, "paid_amount")), "invoice_id": invoice["id"]}
				}
			}
		}
		g["fns"] = Doc{"status": nil, "debts": nil, "checked_at": nil}
		return ok(g)
	}
	filtered := []Doc{}
	for _, g := range out {
		if q := strings.ToLower(r.URL.Query().Get("q")); q != "" && !strings.Contains(strings.ToLower(text(g, "name")), q) {
			continue
		}
		if role := r.URL.Query().Get("role"); role != "" && !strings.Contains(strings.Join(g["roles"].([]string), " "), role) {
			continue
		}
		filtered = append(filtered, g)
	}
	return ok(filtered)
}
func nextOccurrence(after time.Time, period string, dayOfMonth int) time.Time {
	if period == "weekly" {
		return after.AddDate(0, 0, 7)
	}
	if period == "biweekly" {
		return after.AddDate(0, 0, 14)
	}
	months := 1
	if period == "quarterly" {
		months = 3
	}
	candidate := time.Date(after.Year(), after.Month(), 1, 0, 0, 0, 0, time.UTC)
	for i := 0; i < 24; i++ {
		last := candidate.AddDate(0, 1, -1).Day()
		d := dayOfMonth
		if d > last {
			d = last
		}
		if d < 1 {
			d = 1
		}
		v := candidate.AddDate(0, 0, d-1)
		if v.After(after) {
			return v
		}
		candidate = candidate.AddDate(0, months, 0)
	}
	return after.AddDate(0, months, 0)
}
func (s *Service) projectRecurring(ctx context.Context, uid, cid string) error {
	patterns, e := s.DB.ProductList(ctx, uid, cid, "recurring")
	if e != nil {
		return e
	}
	events, e := s.DB.ProductList(ctx, uid, cid, "event")
	if e != nil {
		return e
	}
	exists := map[string]bool{}
	for _, d := range events {
		exists[text(d, "id")] = true
	}
	for _, p := range patterns {
		if !flag(p, "active") {
			continue
		}
		start, e := day(date(p["next_date"]))
		if e != nil {
			return e
		}
		end := today().AddDate(0, 0, 100)
		count := 0
		for start.Before(end) && count < 150 {
			count++
			id := idFor(cid, "recurring:"+text(p, "id")+":"+start.Format(domain.DateLayout))
			if !exists[id] {
				d := Doc{"id": id, "date": start.Format(domain.DateLayout), "title": p["title"], "amount": p["amount"], "direction": p["direction"], "category": p["category"], "counterparty_name": p["counterparty_name"], "probability": float64(1), "status": "expected", "source": "recurring", "recurring_id": p["id"], "origin": p["origin"], "additional": text(p, "origin") == "manual", "occurrence_key": id}
				if _, e = s.DB.ProductSave(ctx, uid, cid, "event", id, d, true); e != nil {
					return e
				}
			}
			next := nextOccurrence(start, text(p, "period"), int(number(p, "day_of_month")))
			if !next.After(start) {
				break
			}
			start = next
		}
	}
	return nil
}
