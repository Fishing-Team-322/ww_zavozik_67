package product

import (
	"context"
	"math"
	"net/http"
	"sort"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/ingest"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

func (s *Service) historyAnalysis(ctx context.Context, op, uid, cid string, r *http.Request) (Result, error) {
	operations, e := s.DB.ProductList(ctx, uid, cid, "operation")
	if e != nil {
		return Result{}, e
	}
	events, e := s.eventRows(ctx, uid, cid)
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
		invoices, err := s.DB.ProductList(ctx, uid, cid, "invoice")
		if err != nil {
			return Result{}, err
		}
		invoiceAmounts := map[string]float64{}
		for _, invoice := range invoices {
			invoiceAmounts[text(invoice, "id")] = number(invoice, "amount")
		}
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
		known := map[string]bool{}
		if operations := domainOperations(operations); len(operations) > 0 {
			for _, flow := range ingest.DailyFlows(operations, operations[0].Date, asOf, nil) {
				known[flow.Date.Format(domain.DateLayout)] = !flow.Missing
			}
		}
		start, _ := day(from)
		stop, _ := day(to)
		if stop.Sub(start).Hours()/24 > 1096 {
			return Result{}, bad("Для графика выберите период до трёх лет")
		}
		for dt := start; !dt.After(stop); dt = dt.AddDate(0, 0, 1) {
			p := key(dt.Format(domain.DateLayout))
			if groups[p] == nil {
				groups[p] = Doc{"period": p, "plan_in": float64(0), "plan_out": float64(0), "fact_in": float64(0), "fact_out": float64(0), "deviation": float64(0), "observed": true, "plan_available": false, "plan_basis": "none"}
			}
			if !known[dt.Format(domain.DateLayout)] {
				groups[p]["observed"] = false
			}
		}
		add := func(dt, k string, n float64) {
			if dt < from || dt > to {
				return
			}
			p := key(dt)
			if groups[p] == nil {
				groups[p] = Doc{"period": p, "plan_in": float64(0), "plan_out": float64(0), "fact_in": float64(0), "fact_out": float64(0), "deviation": float64(0)}
			}
			groups[p][k] = number(groups[p], k) + n
			if k == "plan_in" || k == "plan_out" {
				groups[p]["plan_available"] = true
				groups[p]["plan_basis"] = "documents"
			}
		}
		for _, d := range operations {
			if !flag(d, "is_duplicate") && !flag(d, "is_internal") {
				add(date(d["op_date"]), "fact_"+text(d, "direction"), number(d, "amount"))
			}
		}
		for _, d := range events {
			if !in(text(d, "status"), "cancelled linked") {
				amount := number(d, "amount")
				// Calendar/forecast projections contain the outstanding balance.
				// Plan-fact compares bank facts with the full invoice obligation.
				if text(d, "source_kind") == "invoice" {
					if total, exists := invoiceAmounts[text(d, "document_id")]; exists {
						amount = total
					}
				}
				add(date(d["event_date"]), "plan_"+text(d, "direction"), amount)
			}
		}
		// A model plan is comparable with a bank fact only if it was saved
		// before that day. Never reconstruct a historical prediction today.
		snapshots, err := s.DB.Pool.Query(ctx, `SELECT created_at::date::text,as_of::text,payload FROM forecast_runs WHERE company_id=$1 AND as_of<$2::date ORDER BY created_at`, cid, to)
		if err != nil {
			return Result{}, err
		}
		frozen := map[string]Doc{}
		for snapshots.Next() {
			var created, as string
			var raw []byte
			if err = snapshots.Scan(&created, &as, &raw); err != nil {
				snapshots.Close()
				return Result{}, err
			}
			for _, flow := range docs(store.Decode(raw)["planned_flows"]) {
				dt := text(flow, "date")
				if dt >= from && dt <= to && created < dt && as < dt {
					frozen[dt] = flow
				}
			}
		}
		err = snapshots.Err()
		snapshots.Close()
		if err != nil {
			return Result{}, err
		}
		// Weekly comparisons require a saved plan for every day in the period.
		for period, group := range groups {
			in, out := 0.0, 0.0
			complete, has := true, false
			for dt := start; !dt.After(stop); dt = dt.AddDate(0, 0, 1) {
				date := dt.Format(domain.DateLayout)
				if key(date) != period {
					continue
				}
				flow, exists := frozen[date]
				if !exists {
					complete = false
					continue
				}
				has = true
				in += number(flow, "in")
				out += number(flow, "out")
			}
			if complete && has && !flag(group, "plan_available") {
				group["plan_in"], group["plan_out"], group["plan_available"], group["plan_basis"] = money(in), money(out), true, "forecast"
			}
		}
		out := []Doc{}
		for _, g := range groups {
			g["deviation"] = money(number(g, "fact_in") - number(g, "fact_out") - number(g, "plan_in") + number(g, "plan_out"))
			if !flag(g, "observed") {
				g["fact_in"], g["fact_out"], g["deviation"] = nil, nil, nil
			}
			if !flag(g, "plan_available") {
				g["plan_in"], g["plan_out"], g["deviation"] = nil, nil, nil
			}
			out = append(out, g)
		}
		sort.Slice(out, func(i, j int) bool { return text(out[i], "period") < text(out[j], "period") })
		return ok(out)
	case "getMissedPlanFact":
		missed := []Doc{}
		matched := map[string]bool{}
		settlements, e := s.DB.Pool.Query(ctx, "SELECT operation_id FROM operation_settlements WHERE company_id=$1", cid)
		if e != nil {
			return Result{}, e
		}
		for settlements.Next() {
			var id string
			if e = settlements.Scan(&id); e != nil {
				settlements.Close()
				return Result{}, e
			}
			matched[id] = true
		}
		e = settlements.Err()
		settlements.Close()
		if e != nil {
			return Result{}, e
		}
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
			if !flag(d, "is_internal") && !flag(d, "is_duplicate") && !matched[text(d, "id")] && date(d["op_date"]) >= from && date(d["op_date"]) <= to {
				unexpected = append(unexpected, view("operation", d))
			}
		}
		change, e := s.forecastChange(ctx, cid)
		if e != nil {
			return Result{}, e
		}
		return ok(Doc{"missed": missed, "unexpected": unexpected, "forecast_change": change, "data_as_of": asOf.Format(domain.DateLayout)})
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
		rows, e := s.DB.Pool.Query(ctx, `SELECT p.point_date::text,p.p50::float8,r.as_of::text FROM forecast_points p JOIN forecast_runs r ON r.id=p.run_id WHERE r.company_id=$1 AND p.point_date BETWEEN $2::date AND $3::date AND p.point_date>r.as_of AND r.created_at::date<p.point_date ORDER BY p.point_date,r.created_at`, cid, from, to)
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
		if q.Get("unread") == "false" && !flag(d, "read") {
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
