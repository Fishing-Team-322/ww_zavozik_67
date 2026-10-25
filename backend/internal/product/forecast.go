package product

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"math"
	"net/http"
	"strconv"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/dataset"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/ingest"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/risk"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func horizon(r *http.Request) (int, error) {
	n := 30
	if q := r.URL.Query().Get("horizon"); q != "" {
		v, e := strconv.Atoi(q)
		if e != nil || v < 7 || v > 90 {
			return 0, bad("horizon должен быть от 7 до 90")
		}
		n = v
	}
	return n, nil
}

// A 1C invoice without a due date is stored on its document date for audit,
// but that date must not be presented as an expected payment in the calendar.
func calendarEventOnDate(event Doc, day string) bool {
	if text(event, "status") == "linked" {
		return false
	}
	if text(event, "source_kind") == "onec_odata" && text(event, "due_date") == "" {
		return false
	}
	return date(event["event_date"]) == day
}

func domainOperations(rows []Doc) []domain.Operation {
	out := []domain.Operation{}
	for _, d := range rows {
		if flag(d, "is_duplicate") {
			continue
		}
		dt, e := day(date(d["op_date"]))
		if e != nil {
			continue
		}
		op := domain.Operation{ID: text(d, "id"), CompanyID: text(d, "company_id"), Date: dt, Amount: domain.Money(number(d, "amount")), Direction: domain.Direction(text(d, "direction")), CounterpartyName: domain.Name(text(d, "counterparty_name")), CounterpartyINN: domain.INN(text(d, "counterparty_inn")), Purpose: domain.Purpose(text(d, "purpose")), Category: domain.Category(text(d, "category")), CategoryMethod: domain.CategoryMethod(text(d, "category_method"))}
		if d["balance_eod"] != nil {
			v := domain.Money(number(d, "balance_eod"))
			op.BalanceEOD = &v
		}
		out = append(out, op)
	}
	ingest.SortOps(out)
	return out
}

// An unpaid additional expense remains a debt after its scheduled date. Carry
// it to the first forecast day without changing the audited calendar date.
// Overdue income is not assumed to arrive, and baseline flows are not added twice.
func eventForecastDate(event Doc, asOf time.Time) (time.Time, bool) {
	if !in(text(event, "status"), "expected missed") {
		return time.Time{}, false
	}
	dt, err := day(date(event["event_date"]))
	if err != nil {
		return time.Time{}, false
	}
	if !dt.After(asOf) {
		if text(event, "direction") == "out" && flag(event, "additional") {
			return asOf.AddDate(0, 0, 1), true
		}
		return time.Time{}, false
	}
	return dt, text(event, "status") == "expected"
}

// Use the same event/path draw when a scenario moves a plan into the visible
// horizon. Changing its date must not change the probability of actual payment.
func planPathDeviations(event Doc, asOf time.Time, paths int) []float64 {
	prob := number(event, "probability")
	amount := number(event, "amount")
	if text(event, "direction") == "out" {
		amount = -amount
	}
	values := make([]float64, paths)
	for p := range values {
		hash := sha256.Sum256([]byte(fmt.Sprintf("%s:%s:%d", text(event, "id"), asOf.Format(domain.DateLayout), p)))
		u := float64(binary.LittleEndian.Uint64(hash[:8])) / float64(^uint64(0))
		happens := float64(0)
		if u < prob {
			happens = 1
		}
		values[p] = amount * (happens - prob)
	}
	return values
}

func (s *Service) build(ctx context.Context, uid, cid string, h int, model string, steps, preview []Doc, persist bool) (Doc, forecast.Result, error) {
	var empty forecast.Result
	company, e := s.DB.GetCompany(ctx, uid, cid)
	if e != nil {
		return nil, empty, e
	}
	if e = s.projectRecurring(ctx, uid, cid); e != nil {
		return nil, empty, e
	}
	revision, e := s.DB.ProductRevision(ctx, cid)
	if e != nil {
		return nil, empty, e
	}
	rows, e := s.DB.ProductList(ctx, uid, cid, "operation")
	if e != nil {
		return nil, empty, e
	}
	ops := domainOperations(rows)
	if len(ops) == 0 {
		return nil, empty, platform.Fail(422, "data_required", "Загрузите выписку с операциями и остатком")
	}
	asOf := ops[len(ops)-1].Date
	from := ops[0].Date
	if asOf.Sub(from) > 365*2*24*time.Hour {
		from = asOf.AddDate(-2, 0, 0)
	}
	flows := ingest.DailyFlows(ops, from, asOf, dataset.NotInternal)
	transactions := []forecast.HistoryTransaction{}
	for _, op := range ops {
		if op.Date.Before(from) {
			continue
		}
		ref := cpRef(cid, Doc{"counterparty_inn": string(op.CounterpartyINN), "counterparty_name": string(op.CounterpartyName)})
		transactions = append(transactions, forecast.HistoryTransaction{ID: op.ID, Date: op.Date, Amount: op.Amount, Direction: op.Direction, Category: op.Category, CounterpartyID: text(ref, "id"), Purpose: op.Purpose})
	}
	dataset.FillBalance(flows)
	if len(flows) == 0 || flows[len(flows)-1].Balance == nil {
		return nil, empty, platform.Fail(422, "balance_required", "Для прогноза нужен известный остаток на последнюю дату выписки")
	}
	opening := *flows[len(flows)-1].Balance
	events, e := s.eventRows(ctx, uid, cid)
	if e != nil {
		return nil, empty, e
	}
	for _, change := range preview {
		if id := text(change, "id"); id != "" {
			patch := Doc{}
			for k, v := range change {
				if k != "id" {
					patch[k] = v
				}
			}
			if e = validateResource("event", patch, false); e != nil {
				return nil, empty, e
			}
			found := false
			for _, event := range events {
				if text(event, "id") == id {
					if dt := text(change, "date"); dt != "" {
						event["event_date"] = dt
					}
					for k, v := range change {
						if k != "id" {
							event[k] = v
						}
					}
					if !in(text(event, "direction"), "in out") || !in(text(event, "status"), "expected received missed cancelled") {
						return nil, empty, bad("Некорректное направление или статус события")
					}
					found = true
					break
				}
			}
			if !found {
				return nil, empty, platform.ErrNotFound
			}
		} else {
			if e = validateResource("event", change, true); e != nil {
				return nil, empty, e
			}
			if e = s.prepare(ctx, uid, cid, "event", change, true); e != nil {
				return nil, empty, e
			}
			change["event_date"] = change["date"]
			change["source_kind"] = "manual"
			change["id"] = uuid.NewString()
			events = append(events, change)
		}
	}
	events, e = s.linkPaymentOrders(ctx, uid, cid, events)
	if e != nil {
		return nil, empty, e
	}
	patterns, e := s.DB.ProductList(ctx, uid, cid, "recurring")
	if e != nil {
		return nil, empty, e
	}
	components, coveredRecurring := recurringBaselineComponents(patterns, asOf, h)
	for _, event := range events {
		event["_recurring_replacement"] = coveredRecurring[text(event, "recurring_id")]
		dt, include := eventForecastDate(event, asOf)
		if !include || dt.After(asOf.AddDate(0, 0, h)) {
			continue
		}
		amount := number(event, "amount")
		if text(event, "direction") == "out" {
			amount = -amount
		}
		// Detected recurring replaces its original estimate; other model-covered
		// plans are not added a second time.
		if !flag(event, "additional") && !coveredRecurring[text(event, "recurring_id")] {
			continue
		}
		components = append(components, forecast.ComponentFlow{Date: dt, Key: "event:" + text(event, "id"), Title: text(event, "title"), Amount: domain.Money(amount * number(event, "probability")), Source: domain.SourceKind(text(event, "source_kind"))})
	}
	if model == "" {
		model = "auto"
	}
	fallback := s.Fallback
	if fallback == nil {
		fallback = forecast.SeasonalNaive{}
	}
	res, e := (forecast.Assembler{Primary: incrementalForecaster{db: s.DB, primary: s.ML}, Fallback: fallback, Timeout: 15 * time.Second}).Build(ctx, forecast.Input{AsOf: asOf, OpeningBalance: opening, Deterministic: components, Stochastic: forecast.StochasticRequest{CompanyID: cid, Industry: company.Industry, Model: model, History: flows, Transactions: transactions, Horizon: h, NPaths: 600, Seed: 67, FlowScope: forecast.BusinessFlowScope}})
	if e != nil {
		switch status.Code(e) {
		case codes.InvalidArgument:
			return nil, empty, platform.Fail(400, "invalid_forecast_request", "Модель отклонила параметры запроса")
		case codes.FailedPrecondition:
			return nil, empty, platform.Fail(422, "forecast_precondition", "Для выбранной модели недостаточно наблюдаемых данных или нет обученного артефакта")
		}
		return nil, empty, platform.Fail(502, "forecast_unavailable", "Не удалось рассчитать прогноз")
	}
	res.DataRevision = revision
	for _, event := range events {
		prob := number(event, "probability")
		if !composedEvent(event) || prob <= 0 || prob >= 1 {
			continue
		}
		dt, include := eventForecastDate(event, asOf)
		if !include || res.DayIndex(dt) < 0 {
			continue
		}
		res.Uncertain = append(res.Uncertain, forecast.PathComponent{Date: dt, Key: "event:" + text(event, "id"), Values: planPathDeviations(event, asOf, len(res.Balances))})
	}
	if e = res.Recompute(); e != nil {
		return nil, empty, e
	}
	if len(steps) > 0 {
		res, events, e = s.applyStepsAndEvents(ctx, uid, cid, res, events, steps)
		if e != nil {
			return nil, empty, e
		}
	}
	// Describe the same transformed plans that produced the scenario paths.
	markers := []Doc{}
	carriedExpense := false
	for _, event := range events {
		dt, include := eventForecastDate(event, asOf)
		if !include || dt.After(asOf.AddDate(0, 0, h)) {
			continue
		}
		amount := number(event, "amount")
		if text(event, "direction") == "out" {
			amount = -amount
		}
		title := text(event, "title")
		if date(event["event_date"]) <= asOf.Format(domain.DateLayout) {
			carriedExpense = true
			title += " (не оплачен, срок " + date(event["event_date"]) + ")"
		}
		markers = append(markers, Doc{"date": dt.Format(domain.DateLayout), "title": title, "amount": amount, "kind": text(event, "source_kind")})
	}
	for _, component := range res.Deterministic {
		if component.Key == "scenario:add_expense" && res.DayIndex(component.Date) >= 0 {
			markers = append(markers, Doc{"date": component.Date.Format(domain.DateLayout), "title": component.Title, "amount": component.Amount.Float(), "kind": "manual"})
		}
	}
	q10, q50, q90 := res.Quantile(.1), res.Quantile(.5), res.Quantile(.9)
	points := []Doc{}
	for i, dt := range res.Dates {
		points = append(points, Doc{"date": dt.Format(domain.DateLayout), "p10": money(q10[i]), "p50": money(q50[i]), "p90": money(q90[i]), "is_workday": isWorkday(dt)})
	}
	gaps := []Doc{}
	state, headline := "ok", "По прогнозу денег хватает"
	for _, g := range risk.FindGaps(res, domain.Money(company.Reserve)) {
		state = "warning"
		if g.Probability >= .5 {
			state = "danger"
		}
		explanation, causes := explainGap(res, g.Date, company.Reserve)
		gaps = append(gaps, Doc{"id": g.ID, "date": g.Date.Format(domain.DateLayout), "shortfall": money(g.Shortfall.Float()), "shortfall_p90": money(g.ShortfallP90.Float()), "probability": g.Probability, "days_left": int(g.Date.Sub(asOf).Hours() / 24), "headline": "Остаток может опуститься ниже резерва", "worst_date": explanation["date"], "probability_on_date": explanation["probability_on_first_date"], "explanation": explanation, "causes": causes})
		headline = "Есть риск, что денег не хватит"
	}
	history := []Doc{}
	start := len(flows) - 30
	if start < 0 {
		start = 0
	}
	for _, f := range flows[start:] {
		var b any
		if f.Balance != nil {
			b = f.Balance.Float()
		}
		history = append(history, Doc{"date": f.Date.Format(domain.DateLayout), "balance": b})
	}
	warnings := append([]string{}, res.Stochastic.Warnings...)
	for _, event := range events {
		dt, included := eventForecastDate(event, asOf)
		if text(event, "data_mode") == "demo" && flag(event, "additional") && included && !dt.After(asOf.AddDate(0, 0, h)) {
			warnings = append(warnings, "demonstration_obligations_included")
			break
		}
	}
	if carriedExpense {
		warnings = append(warnings, "overdue_additional_expenses_carried_forward")
	}
	if today().Sub(asOf) > 7*24*time.Hour {
		warnings = append(warnings, "stale_statement_forecast_starts_after_data_as_of")
	}
	out := Doc{"as_of": asOf.Format(domain.DateLayout), "horizon": h, "model_used": res.Stochastic.ModelUsed, "model_version": res.Stochastic.ModelVersion, "flow_scope": res.Stochastic.FlowScope, "fallback_used": res.Stochastic.FallbackUsed, "warnings": warnings, "low_confidence": res.Stochastic.LowConfidence, "opening_balance": opening.Float(), "safe_to_spend": money(risk.SafeToSpend(res, domain.Money(company.Reserve), .1).Float()), "status": state, "headline": headline, "history": history, "points": points, "markers": markers, "gaps": gaps}
	out["update_mode"], out["model_as_of"] = res.Stochastic.UpdateMode, res.Stochastic.BaseAsOf
	if persist {
		if e = s.persistForecast(ctx, uid, cid, revision, out); e != nil {
			return nil, empty, e
		}
	}
	return out, res, nil
}
func (s *Service) persistForecast(ctx context.Context, uid, cid string, rev int64, out Doc) error {
	tx, e := s.DB.Pool.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	var current int64
	if e = tx.QueryRow(ctx, "SELECT data_revision FROM companies WHERE id=$1 FOR UPDATE", cid).Scan(&current); e != nil {
		return e
	}
	if current != rev {
		return platform.Fail(409, "version_conflict", "Данные изменились во время расчёта. Повторите запрос")
	}
	id := uuid.NewString()
	_, e = tx.Exec(ctx, `INSERT INTO forecast_runs(id,company_id,as_of,horizon,model_used,low_confidence,opening_balance,safe_to_spend,revision,payload) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, id, cid, text(out, "as_of"), int(number(out, "horizon")), text(out, "model_used"), flag(out, "low_confidence"), number(out, "opening_balance"), number(out, "safe_to_spend"), rev, string(store.JSON(out)))
	if e != nil {
		return e
	}
	for _, p := range docs(out["points"]) {
		if _, e = tx.Exec(ctx, "INSERT INTO forecast_points(run_id,point_date,p10,p50,p90) VALUES($1,$2,$3,$4,$5)", id, text(p, "date"), number(p, "p10"), number(p, "p50"), number(p, "p90")); e != nil {
			return e
		}
	}
	for _, g := range docs(out["gaps"]) {
		if _, e = tx.Exec(ctx, "INSERT INTO gaps(id,run_id,gap_date,shortfall,shortfall_p90,probability) VALUES($1,$2,$3,$4,$5,$6)", text(g, "id"), id, text(g, "date"), number(g, "shortfall"), number(g, "shortfall_p90"), number(g, "probability")); e != nil {
			return e
		}
	}
	return tx.Commit(ctx)
}
func (s *Service) financial(ctx context.Context, op, uid, cid string, r *http.Request, b Doc) (Result, error) {
	switch op {
	case "getPlanFact", "getMissedPlanFact", "getRetro", "getForecastAccuracy":
		return s.historyAnalysis(ctx, op, uid, cid, r)
	}
	h, e := horizon(r)
	if e != nil {
		return Result{}, e
	}
	if op == "getCalendar" {
		h = 90
	}
	steps := []Doc{}
	if sid := r.URL.Query().Get("scenario"); sid != "" {
		d, e := s.DB.ProductGet(ctx, uid, "scenario", sid)
		if e != nil {
			return Result{}, e
		}
		if text(d, "company_id") != cid {
			return Result{}, platform.ErrNotFound
		}
		steps = docs(d["steps"])
	}
	preview := []Doc{}
	if op == "previewForecast" {
		if e = fields(b, "changes events"); e != nil {
			return Result{}, e
		}
		for _, key := range []string{"changes", "events"} {
			value, provided := b[key]
			if !provided {
				continue
			}
			items, valid := value.([]any)
			if !valid {
				return Result{}, bad(key + ": нужен массив объектов")
			}
			if len(preview)+len(items) > 100 {
				return Result{}, bad("Слишком много изменений")
			}
			for _, item := range items {
				change, valid := item.(map[string]any)
				if !valid {
					return Result{}, bad(key + ": каждый элемент должен быть объектом")
				}
				preview = append(preview, Doc(change))
			}
		}
	}
	out, res, e := s.build(ctx, uid, cid, h, r.URL.Query().Get("model"), steps, preview, op == "getForecast" && len(steps) == 0)
	if e != nil {
		if op == "getDashboard" && platform.IsStatus(e, 422) {
			return ok(Doc{"status": "empty", "headline": "Загрузите выписку для прогноза", "balance_now": nil, "safe_to_spend": nil, "min_balance": nil, "low_confidence": true, "data_as_of": nil, "forecast": nil, "upcoming_out": []Doc{}, "upcoming_in": []Doc{}, "alerts": []Doc{}, "top_gap": nil})
		}
		if op == "getCalendar" && platform.IsStatus(e, 422) {
			out = Doc{"points": []Doc{}}
		} else {
			return Result{}, e
		}
	}
	switch op {
	case "getForecast":
		return ok(out)
	case "getForecastDay":
		dt := r.PathValue("date")
		for _, p := range docs(out["points"]) {
			if text(p, "date") == dt {
				parts := []Doc{}
				dayDate, _ := day(dt)
				dayIndex := res.DayIndex(dayDate)
				mean := float64(0)
				for path := range res.Stochastic.Inflow {
					mean += res.Stochastic.Inflow[path][dayIndex] - res.Stochastic.Outflow[path][dayIndex]
				}
				mean /= float64(len(res.Stochastic.Inflow))
				parts = append(parts, Doc{"title": "Ожидаемый поток бизнеса по модели", "amount": money(mean), "kind": "model", "source": out["model_used"]})
				for _, c := range res.Deterministic {
					if c.Date.Format(domain.DateLayout) == dt {
						parts = append(parts, Doc{"title": c.Title, "amount": c.Amount.Float(), "kind": "event", "source": string(c.Source)})
					}
				}
				p["components"] = parts
				p["components_basis"] = "mean_daily_flows; balance_quantiles_are_path_quantiles"
				return ok(p)
			}
		}
		return Result{}, platform.ErrNotFound
	case "getDashboard":
		points := docs(out["points"])
		var min Doc
		for _, p := range points {
			if min == nil || number(p, "p50") < number(min, "p50") {
				min = Doc{"date": p["date"], "p50": p["p50"]}
			}
		}
		var top any
		if gs := docs(out["gaps"]); len(gs) > 0 {
			top = gs[0]
		}
		events, e := s.eventRows(ctx, uid, cid)
		if e != nil {
			return Result{}, e
		}
		ins, outs := []Doc{}, []Doc{}
		until := res.AsOf.AddDate(0, 0, 14).Format(domain.DateLayout)
		for _, d := range events {
			if date(d["event_date"]) > text(out, "as_of") && date(d["event_date"]) <= until && text(d, "status") == "expected" {
				if text(d, "direction") == "in" {
					v := view("event", d)
					v["payer_habit"] = nil
					ins = append(ins, v)
				} else {
					outs = append(outs, view("event", d))
				}
			}
		}
		alerts, e := s.DB.ProductList(ctx, uid, cid, "alert")
		if e != nil {
			return Result{}, e
		}
		av := []Doc{}
		for _, a := range alerts {
			if len(av) < 5 {
				av = append(av, view("alert", a))
			}
		}
		return ok(Doc{"status": out["status"], "headline": out["headline"], "balance_now": out["opening_balance"], "safe_to_spend": out["safe_to_spend"], "min_balance": min, "low_confidence": out["low_confidence"], "data_as_of": out["as_of"], "forecast": out, "upcoming_in": ins, "upcoming_out": outs, "alerts": av, "top_gap": top})
	case "getCalendar":
		month := r.URL.Query().Get("month")
		start, e := time.Parse("2006-01", month)
		if e != nil {
			return Result{}, bad("month должен быть YYYY-MM")
		}
		events, e := s.eventRows(ctx, uid, cid)
		if e != nil {
			return Result{}, e
		}
		index := map[string]Doc{}
		for _, p := range docs(out["points"]) {
			index[text(p, "date")] = p
		}
		company, e := s.DB.GetCompany(ctx, uid, cid)
		if e != nil {
			return Result{}, e
		}
		days := []Doc{}
		for dt := start; dt.Month() == start.Month(); dt = dt.AddDate(0, 0, 1) {
			key := dt.Format(domain.DateLayout)
			items := []Doc{}
			for _, event := range events {
				if calendarEventOnDate(event, key) {
					items = append(items, view("event", event))
				}
			}
			var bal any
			state := "unknown"
			if point := index[key]; point != nil {
				bal = point["p50"]
				state = "ok"
				if number(point, "p10") < company.Reserve {
					state = "warning"
				}
				if number(point, "p50") < company.Reserve {
					state = "danger"
				}
			}
			days = append(days, Doc{"date": key, "is_workday": isWorkday(dt), "balance_p50": bal, "risk": state, "events": items})
		}
		return ok(Doc{"days": days, "calendar_source": "ru_production_calendar_2024_2027_weekdays_fallback_outside_range"})
	case "previewForecast":
		base, _, e := s.build(ctx, uid, cid, h, "auto", nil, nil, false)
		if e != nil {
			return Result{}, e
		}
		return ok(Doc{"forecast": out, "diff": forecastDelta(base, out)})
	case "getGap", "simulateGap":
		var gap Doc
		for _, g := range docs(out["gaps"]) {
			if text(g, "id") == r.PathValue("gapId") {
				gap = g
				break
			}
		}
		if gap == nil {
			return Result{}, platform.ErrNotFound
		}
		return s.gapResult(ctx, op, uid, cid, gap, out, res, b)
	}
	return Result{}, bad("Неизвестный расчёт")
}
func forecastDelta(base, other Doc) Doc {
	min := func(d Doc) float64 {
		v := math.Inf(1)
		for _, p := range docs(d["points"]) {
			v = math.Min(v, number(p, "p50"))
		}
		if math.IsInf(v, 1) {
			return 0
		}
		return v
	}
	bg, sg := docs(base["gaps"]), docs(other["gaps"])
	bp, sp, bs, ss := float64(0), float64(0), float64(0), float64(0)
	var gd any
	if len(bg) > 0 {
		bp = number(bg[0], "probability")
		bs = number(bg[0], "shortfall")
	}
	if len(sg) > 0 {
		sp = number(sg[0], "probability")
		ss = number(sg[0], "shortfall")
		gd = sg[0]["date"]
	}
	return Doc{"min_balance": money(min(other) - min(base)), "gap_date": gd, "shortfall": money(ss - bs), "probability": sp - bp, "probability_before": bp, "probability_after": sp, "gap_closed": len(bg) > 0 && len(sg) == 0, "new_gaps": sg}
}
