package product

import (
	"context"
	"math"
	"net/http"
	"sort"
	"strconv"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

func (s *Service) historyAnalysis(ctx context.Context, op, uid, cid string, r *http.Request) (Result, error) {
	operations, e := s.DB.ProductList(ctx, uid, cid, "operation")
	if e != nil {
		return Result{}, e
	}
	events, e := s.DB.ProductList(ctx, uid, cid, "event")
	if e != nil {
		return Result{}, e
	}
	asOf := today()
	if rows := domainOperations(operations); len(rows) > 0 {
		asOf = rows[len(rows)-1].Date
	}
	from, to, e := rangeDates(r)
	if e != nil {
		return Result{}, e
	}
	if to == "" {
		to = asOf.Format(domain.DateLayout)
	}
	if from == "" {
		from = asOf.AddDate(0, 0, -30).Format(domain.DateLayout)
	}
	switch op {
	case "getPlanFact":
		gran := r.URL.Query().Get("granularity")
		if gran == "" {
			gran = "day"
		}
		if !in(gran, "day week") {
			return Result{}, bad("granularity: day или week")
		}
		key := func(dt string) string {
			if gran == "day" {
				return dt
			}
			d, _ := day(dt)
			offset := (int(d.Weekday()) + 6) % 7
			return d.AddDate(0, 0, -offset).Format(domain.DateLayout)
		}
		groups := map[string]Doc{}
		add := func(dt, k string, n float64) {
			if dt < from || dt > to {
				return
			}
			p := key(dt)
			if groups[p] == nil {
				groups[p] = Doc{"period": p, "plan_in": float64(0), "plan_out": float64(0), "fact_in": float64(0), "fact_out": float64(0), "deviation": float64(0)}
			}
			groups[p][k] = number(groups[p], k) + n
		}
		for _, d := range operations {
			if !flag(d, "is_duplicate") && !flag(d, "is_internal") {
				add(date(d["op_date"]), "fact_"+text(d, "direction"), number(d, "amount"))
			}
		}
		for _, d := range events {
			if text(d, "status") != "cancelled" {
				add(date(d["event_date"]), "plan_"+text(d, "direction"), number(d, "amount"))
			}
		}
		out := []Doc{}
		for _, g := range groups {
			g["deviation"] = money(number(g, "fact_in") - number(g, "fact_out") - number(g, "plan_in") + number(g, "plan_out"))
			out = append(out, g)
		}
		sort.Slice(out, func(i, j int) bool { return text(out[i], "period") < text(out[j], "period") })
		return ok(out)
	case "getMissedPlanFact":
		missed := []Doc{}
		matched := map[string]bool{}
		for _, d := range events {
			if id := text(d, "matched_operation_id"); id != "" {
				matched[id] = true
			}
			if text(d, "status") == "missed" && date(d["event_date"]) >= from && date(d["event_date"]) <= to {
				v := view("event", d)
				dt, _ := day(date(d["event_date"]))
				v["days_late"] = int(asOf.Sub(dt).Hours() / 24)
				missed = append(missed, v)
			}
		}
		unexpected := []Doc{}
		for _, d := range operations {
			if !matched[text(d, "id")] && date(d["op_date"]) >= from && date(d["op_date"]) <= to {
				unexpected = append(unexpected, view("operation", d))
			}
		}
		return ok(Doc{"missed": missed, "unexpected": unexpected, "forecast_change": Doc{"gap_date": nil, "probability_before": nil, "probability_after": nil}, "data_as_of": asOf.Format(domain.DateLayout)})
	case "getTaxes":
		months := 3
		if raw := r.URL.Query().Get("months"); raw != "" {
			n, e := strconv.Atoi(raw)
			if e != nil || n < 1 || n > 12 {
				return Result{}, bad("months должен быть от 1 до 12")
			}
			months = n
		}
		patterns, e := s.DB.ProductList(ctx, uid, cid, "recurring")
		if e != nil {
			return Result{}, e
		}
		company, e := s.DB.GetCompany(ctx, uid, cid)
		if e != nil {
			return Result{}, e
		}
		items := []Doc{}
		until := today().AddDate(0, months, 0)
		for _, p := range patterns {
			if text(p, "category") != "tax" || !flag(p, "active") || !flag(p, "confirmed") {
				continue
			}
			dt, e := day(date(p["next_date"]))
			if e != nil {
				return Result{}, e
			}
			for i := 0; i < 100 && dt.Before(until); i++ {
				if !dt.Before(today()) {
					items = append(items, Doc{"date": dt.Format(domain.DateLayout), "title": p["title"], "amount_estimate": p["amount"], "how_calculated": "Проекция подтверждённого регулярного платежа; налоговая декларация и расчёт по ставке не выполнялись"})
				}
				dt = nextOccurrence(dt, text(p, "period"), int(number(p, "day_of_month")))
			}
		}
		return ok(Doc{"tax_regime": company.TaxRegime, "regime_detected": nil, "items": items, "calculation_basis": "confirmed_recurring_payments"})
	case "getRetro":
		company, e := s.DB.GetCompany(ctx, uid, cid)
		if e != nil {
			return Result{}, e
		}
		items, series := []Doc{}, []Doc{}
		injected := float64(0)
		balances := map[string]float64{}
		for _, d := range operations {
			kind := text(d, "category")
			if kind == "owner_loan" || kind == "own_transfer" {
				if text(d, "direction") == "in" {
					items = append(items, Doc{"date": date(d["op_date"]), "amount": d["amount"], "kind": kind, "warned_days_before": nil})
					if kind == "owner_loan" {
						injected += number(d, "amount")
					}
				}
			}
			if d["balance_eod"] != nil {
				balances[date(d["op_date"])] = number(d, "balance_eod")
			}
		}
		for dt, bal := range balances {
			series = append(series, Doc{"date": dt, "balance": bal})
			if bal < company.Reserve {
				items = append(items, Doc{"date": dt, "amount": money(company.Reserve - bal), "kind": "below_reserve", "warned_days_before": nil})
			}
		}
		sort.Slice(series, func(i, j int) bool { return text(series[i], "date") < text(series[j], "date") })
		// Only predictions actually saved before an event count as an advance warning.
		runs, e := s.DB.Pool.Query(ctx, "SELECT as_of::text,created_at::date::text,payload FROM forecast_runs WHERE company_id=$1 ORDER BY created_at", cid)
		if e != nil {
			return Result{}, e
		}
		defer runs.Close()
		for runs.Next() {
			var as, created string
			var raw []byte
			if e = runs.Scan(&as, &created, &raw); e != nil {
				return Result{}, e
			}
			for _, item := range items {
				dt := text(item, "date")
				if as >= dt || created >= dt {
					continue
				}
				for _, gap := range docs(store.Decode(raw)["gaps"]) {
					if text(gap, "date") == dt && number(gap, "probability") >= .5 {
						a, _ := day(created)
						b, _ := day(dt)
						lead := b.Sub(a).Hours() / 24
						if item["warned_days_before"] == nil || number(item, "warned_days_before") < lead {
							item["warned_days_before"] = lead
						}
					}
				}
			}
		}
		if e = runs.Err(); e != nil {
			return Result{}, e
		}
		detected, totalLead := 0, float64(0)
		for _, item := range items {
			if item["warned_days_before"] != nil {
				detected++
				totalLead += number(item, "warned_days_before")
			}
		}
		var avg any
		if detected > 0 {
			avg = money(totalLead / float64(detected))
		}
		return ok(Doc{"events": len(items), "detected": detected, "avg_lead_days": avg, "owner_injections_total": money(injected), "items": items, "series": series, "warning": "Lead time counts only stored predictions made before the event, probability >= 0.5"})
	case "getForecastAccuracy":
		rows, e := s.DB.Pool.Query(ctx, `SELECT p.point_date::text,p.p50::float8,r.as_of::text FROM forecast_points p JOIN forecast_runs r ON r.id=p.run_id WHERE r.company_id=$1 AND p.point_date BETWEEN $2::date AND $3::date AND p.point_date>r.as_of ORDER BY p.point_date,r.created_at`, cid, from, to)
		if e != nil {
			return Result{}, e
		}
		defer rows.Close()
		actual := map[string]float64{}
		for _, d := range operations {
			if d["balance_eod"] != nil {
				actual[date(d["op_date"])] = number(d, "balance_eod")
			}
		}
		items := []Doc{}
		sum := float64(0)
		for rows.Next() {
			var dt, as string
			var pred float64
			if e = rows.Scan(&dt, &pred, &as); e != nil {
				return Result{}, e
			}
			if fact, yes := actual[dt]; yes {
				err := math.Abs(pred - fact)
				sum += err
				items = append(items, Doc{"date": dt, "as_of": as, "forecast": pred, "actual": fact, "absolute_error": money(err)})
			}
		}
		if e = rows.Err(); e != nil {
			return Result{}, e
		}
		var mean any
		if len(items) > 0 {
			mean = money(sum / float64(len(items)))
		}
		return ok(Doc{"items": items, "mean_absolute_error": mean, "samples": len(items)})
	}
	return Result{}, bad("Неизвестный анализ")
}
func (s *Service) alerts(ctx context.Context, op, uid, cid string, r *http.Request) (Result, error) {
	rows, e := s.DB.ProductList(ctx, uid, cid, "alert")
	if e != nil {
		return Result{}, e
	}
	out := []Doc{}
	unread := 0
	for _, d := range rows {
		if !flag(d, "read") {
			unread++
		}
		if op == "readAllAlerts" {
			if !flag(d, "read") {
				d["read"] = true
				if _, e = s.DB.ProductSave(ctx, uid, cid, "alert", text(d, "id"), d, false); e != nil {
					return Result{}, e
				}
			}
			continue
		}
		q := r.URL.Query()
		if v := q.Get("severity"); v != "" && text(d, "severity") != v {
			continue
		}
		if v := q.Get("kind"); v != "" && text(d, "kind") != v {
			continue
		}
		if q.Get("unread") == "true" && flag(d, "read") {
			continue
		}
		out = append(out, view("alert", d))
	}
	if op == "readAllAlerts" {
		return Result{Status: 204}, nil
	}
	p, e := page(out, r)
	if e != nil {
		return Result{}, e
	}
	p["unread_count"] = unread
	return ok(p)
}
