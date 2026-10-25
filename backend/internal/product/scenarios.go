package product

import (
	"context"
	"crypto/sha256"
	"fmt"
	"math"
	"net/http"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

func ScenarioPresets() []Doc {
	return []Doc{
		{"kind": "delay_counterparty", "title": "Клиент заплатит позже", "description": "Перенести известные плановые поступления клиента", "params_schema": Doc{"counterparty_id": "uuid", "delay_days": "integer"}},
		{"kind": "scale_revenue", "title": "Выручка изменится", "description": "Изменить прогноз поступлений на выбранную долю", "params_schema": Doc{"factor": "number"}},
		{"kind": "add_expense", "title": "Новая покупка", "description": "Добавить разовый расход", "params_schema": Doc{"amount": "number", "date": "date"}},
		{"kind": "scale_fixed_costs", "title": "Постоянные расходы изменятся", "description": "Изменить известные регулярные расходы", "params_schema": Doc{"factor": "number"}},
	}
}
func validateSteps(steps []Doc) error {
	if len(steps) == 0 || len(steps) > 100 {
		return bad("Сценарий должен содержать от 1 до 100 шагов")
	}
	for _, step := range steps {
		if e := fields(step, "kind counterparty_id counterparty_name delay_days factor amount date event_id"); e != nil {
			return e
		}
		kind := text(step, "kind")
		switch kind {
		case "scale_revenue", "scale_fixed_costs":
			factor, yes := step["factor"].(float64)
			if !yes || math.IsNaN(factor) || factor < 0 || factor > 10 {
				return bad("factor должен быть от 0 до 10")
			}
		case "add_expense":
			amount, yes := step["amount"].(float64)
			if !yes || math.IsNaN(amount) || math.IsInf(amount, 0) || amount < 0 || amount > 1e13 || math.Abs(amount*100-math.Round(amount*100)) > .001 {
				return bad("Некорректная сумма расхода")
			}
			if _, e := day(text(step, "date")); e != nil {
				return e
			}
		case "move_event":
			if text(step, "event_id") == "" {
				return bad("Нужен event_id")
			}
			if _, e := day(text(step, "date")); e != nil {
				return e
			}
		case "delay_counterparty":
			n, yes := step["delay_days"].(float64)
			if !yes || n != math.Trunc(n) || n < 0 || n > 365 {
				return bad("delay_days должен быть от 0 до 365")
			}
			if text(step, "counterparty_id") == "" && text(step, "counterparty_name") == "" {
				return bad("Нужен контрагент")
			}
		default:
			return bad("Неизвестный вид сценария")
		}
	}
	return nil
}
func (s *Service) applySteps(ctx context.Context, uid, cid string, base forecast.Result, events, steps []Doc) (forecast.Result, error) {
	result, _, err := s.applyStepsAndEvents(ctx, uid, cid, base, events, steps)
	return result, err
}

func (s *Service) applyStepsAndEvents(ctx context.Context, uid, cid string, base forecast.Result, events, steps []Doc) (forecast.Result, []Doc, error) {
	if e := validateSteps(steps); e != nil {
		return forecast.Result{}, nil, e
	}
	out := base.Clone()
	// Scenario steps compose over private event state. Dates and amounts from
	// earlier steps must be visible to later steps, without editing real plans.
	states := make([]Doc, 0, len(events))
	for _, event := range events {
		copy := Doc{}
		for key, value := range event {
			copy[key] = value
		}
		states = append(states, copy)
	}
	events = states
	isRevenue := func(event Doc) bool {
		return text(event, "direction") == "in" && !domain.Category(text(event, "category")).IsInternal()
	}
	revenueKeys := map[string]bool{}
	for _, flow := range out.Deterministic {
		revenueKeys[flow.Key] = flow.Amount > 0
		if strings.HasPrefix(flow.Key, "recurring:baseline:") {
			revenueKeys[flow.Key] = strings.HasPrefix(flow.Key, "recurring:baseline:in:")
		}
	}
	for _, event := range events {
		revenueKeys["event:"+text(event, "id")] = isRevenue(event)
	}
	move := func(event Doc, target time.Time) error {
		old, included := eventForecastDate(event, out.AsOf)
		if !included || !target.After(out.AsOf) {
			return bad("Перенос доступен только для неоплаченного планового платежа на будущую дату")
		}
		amount := number(event, "amount")
		if text(event, "direction") == "out" {
			amount = -amount
		}
		key := "event:" + text(event, "id")
		found := false
		for i := range out.Deterministic {
			if out.Deterministic[i].Key == key || out.Deterministic[i].Key == "delta:new:"+key {
				out.Deterministic[i].Date = target
				found = true
			}
		}
		if !found && composedEvent(event) {
			// Plans originally outside this horizon have no assembled component
			// yet. Introduce their expected flow and per-path uncertainty together.
			prob := number(event, "probability")
			out.Deterministic = append(out.Deterministic, forecast.ComponentFlow{Date: target, Key: key, Title: text(event, "title"), Amount: domain.Money(amount * prob), Source: domain.SourceKind(text(event, "source_kind"))})
			if prob > 0 && prob < 1 {
				out.Uncertain = append(out.Uncertain, forecast.PathComponent{Date: target, Key: key, Values: planPathDeviations(event, out.AsOf, len(out.Balances))})
			}
		} else if !found {
			out.Deterministic = append(out.Deterministic, forecast.ComponentFlow{Date: old, Key: "delta:old:" + key, Title: text(event, "title"), Amount: domain.Money(-amount)}, forecast.ComponentFlow{Date: target, Key: "delta:new:" + key, Title: text(event, "title"), Amount: domain.Money(amount)})
			// A positive reversal of an expense is not revenue. Both legs of
			// a moved receipt, including its negative offset, scale together.
			revenueKeys["delta:old:"+key], revenueKeys["delta:new:"+key] = isRevenue(event), isRevenue(event)
		}
		for i := range out.Uncertain {
			if out.Uncertain[i].Key == key {
				out.Uncertain[i].Date = target
			}
		}
		event["event_date"] = target.Format(domain.DateLayout)
		return nil
	}
	for _, step := range steps {
		switch text(step, "kind") {
		case "scale_revenue":
			factor := number(step, "factor")
			for i := range out.Uncertain {
				if revenueKeys[out.Uncertain[i].Key] {
					for p := range out.Uncertain[i].Values {
						out.Uncertain[i].Values[p] *= factor
					}
				}
			}
			for p := range out.Stochastic.Inflow {
				for d := range out.Stochastic.Inflow[p] {
					out.Stochastic.Inflow[p][d] *= factor
				}
			}
			for i := range out.Deterministic {
				if revenueKeys[out.Deterministic[i].Key] {
					out.Deterministic[i].Amount *= domain.Money(factor)
				}
			}
			for _, event := range events {
				if isRevenue(event) {
					event["amount"] = number(event, "amount") * factor
				}
			}
		case "add_expense":
			dt, _ := day(text(step, "date"))
			if !dt.After(out.AsOf) {
				return forecast.Result{}, nil, bad("Расход сценария должен быть после последней даты выписки")
			}
			out.Deterministic = append(out.Deterministic, forecast.ComponentFlow{Date: dt, Key: "scenario:add_expense", Title: "Дополнительный расход", Amount: domain.Money(-number(step, "amount")), Source: domain.SrcManual})
		case "move_event":
			found := false
			for _, event := range events {
				if text(event, "id") == text(step, "event_id") {
					dt, _ := day(text(step, "date"))
					if e := move(event, dt); e != nil {
						return forecast.Result{}, nil, e
					}
					found = true
					break
				}
			}
			if !found {
				return forecast.Result{}, nil, platform.ErrNotFound
			}
		case "delay_counterparty":
			found := false
			for _, event := range events {
				ref := cpRef(cid, event)
				selectedID := text(step, "counterparty_id")
				matches := selectedID != "" && ref["id"] == selectedID
				if selectedID == "" {
					matches = strings.EqualFold(text(event, "counterparty_name"), text(step, "counterparty_name"))
				}
				if matches {
					if text(event, "direction") != "in" || text(event, "status") != "expected" {
						continue
					}
					if _, included := eventForecastDate(event, out.AsOf); !included {
						continue
					}
					dt, _ := day(date(event["event_date"]))
					if e := move(event, dt.AddDate(0, 0, int(number(step, "delay_days")))); e != nil {
						return forecast.Result{}, nil, e
					}
					found = true
				}
			}
			if !found {
				return forecast.Result{}, nil, platform.Fail(422, "planned_receipt_required", "Для переноса нужны плановые поступления выбранного клиента")
			}
		case "scale_fixed_costs":
			for _, event := range events {
				if text(event, "source_kind") != "recurring" || text(event, "direction") != "out" || text(event, "status") != "expected" {
					continue
				}
				dt, _ := day(date(event["event_date"]))
				if !dt.After(out.AsOf) {
					continue
				}
				factor := number(step, "factor")
				key := "event:" + text(event, "id")
				explicit := false
				for i := range out.Deterministic {
					if out.Deterministic[i].Key == key || out.Deterministic[i].Key == "delta:new:"+key {
						out.Deterministic[i].Amount *= domain.Money(factor)
						explicit = true
					}
				}
				for i := range out.Uncertain {
					if out.Uncertain[i].Key == key {
						for p := range out.Uncertain[i].Values {
							out.Uncertain[i].Values[p] *= factor
						}
					}
				}
				if !explicit {
					delta := -number(event, "amount") * (factor - 1)
					out.Deterministic = append(out.Deterministic, forecast.ComponentFlow{Date: dt, Key: "scenario:fixed:" + text(event, "id"), Title: text(event, "title"), Amount: domain.Money(delta)})
				}
				event["amount"] = number(event, "amount") * factor
			}
		}
	}
	return out, events, out.Recompute()
}
func (s *Service) compare(ctx context.Context, op, uid, cid string, r *http.Request, b Doc) (Result, error) {
	steps := docs(b["steps"])
	if op != "previewScenario" {
		d, e := s.DB.ProductGet(ctx, uid, "scenario", r.PathValue("scenarioId"))
		if e != nil {
			return Result{}, e
		}
		if cid != "" && text(d, "company_id") != cid {
			return Result{}, platform.ErrNotFound
		}
		cid = text(d, "company_id")
		steps = docs(d["steps"])
	}
	if e := validateSteps(steps); e != nil {
		return Result{}, e
	}
	h, e := horizon(r)
	if e != nil {
		return Result{}, e
	}
	from, to := r.URL.Query().Get("from"), r.URL.Query().Get("to")
	if from != "" || to != "" {
		start, startErr := day(from)
		end, endErr := day(to)
		if startErr != nil || endErr != nil || end.Sub(start) != 29*24*time.Hour {
			return Result{}, bad("Выберите период из 30 календарных дней")
		}
		h = 90
	}
	base, basePaths, e := s.build(ctx, uid, cid, h, "auto", nil, nil, false)
	if e != nil {
		return Result{}, e
	}
	if from != "" {
		if len(basePaths.Dates) == 0 || from < basePaths.Dates[0].Format(domain.DateLayout) || to > basePaths.Dates[len(basePaths.Dates)-1].Format(domain.DateLayout) {
			return Result{}, bad("Период должен находиться внутри доступного прогноза на 90 дней")
		}
	}
	other, otherPaths, e := s.build(ctx, uid, cid, h, "auto", steps, nil, false)
	if e != nil {
		return Result{}, e
	}
	if basePaths.DataRevision != otherPaths.DataRevision || !basePaths.AsOf.Equal(otherPaths.AsOf) || len(basePaths.Dates) != len(otherPaths.Dates) {
		return Result{}, platform.Fail(409, "data_changed", "Данные компании изменились во время расчёта. Повторите сравнение.")
	}
	for i := range basePaths.Dates {
		if !basePaths.Dates[i].Equal(otherPaths.Dates[i]) {
			return Result{}, platform.Fail(409, "data_changed", "Даты прогноза изменились. Повторите сравнение.")
		}
	}
	if from != "" {
		start, _ := day(from)
		end, _ := day(to)
		if otherPaths.DayIndex(start) < 0 || otherPaths.DayIndex(end) < 0 {
			return Result{}, platform.Fail(409, "data_changed", "Период больше не доступен. Повторите сравнение.")
		}
		company, err := s.DB.GetCompany(ctx, uid, cid)
		if err != nil {
			return Result{}, err
		}
		base = s.scenarioWindow(base, basePaths, company.Reserve, from, to)
		other = s.scenarioWindow(other, otherPaths, company.Reserve, from, to)
	}
	return ok(Doc{"base": base, "scenario": other, "delta": forecastDelta(base, other)})
}

// Keep the cumulative model balances from before the window. Recomputing paths
// from the statement balance at the selected start would erase earlier flows.
func (s *Service) scenarioWindow(out Doc, paths forecast.Result, reserve float64, from, to string) Doc {
	start, _ := day(from)
	end, _ := day(to)
	i, j := paths.DayIndex(start), paths.DayIndex(end)+1
	window := paths.Clone()
	window.Dates = window.Dates[i:j]
	for p := range window.Balances {
		window.Balances[p] = window.Balances[p][i:j]
	}
	prefix := paths.Clone()
	prefix.Dates = prefix.Dates[:j]
	for p := range prefix.Balances {
		prefix.Balances[p] = prefix.Balances[p][:j]
	}
	for _, field := range []string{"points", "markers", "planned_flows"} {
		selected := []Doc{}
		for _, point := range docs(out[field]) {
			if date := text(point, "date"); date >= from && date <= to {
				selected = append(selected, point)
			}
		}
		out[field] = selected
	}
	out["history"] = []Doc{}
	out["gaps"] = s.gapDocuments(window, reserve, prefix)
	out["status"], out["headline"] = "ok", "По прогнозу денег хватает"
	for _, gap := range docs(out["gaps"]) {
		out["status"], out["headline"] = "warning", "Есть риск, что денег не хватит"
		if number(gap, "probability") >= .5 {
			out["status"] = "danger"
		}
	}
	out["horizon"], out["forecast_end"] = j-i, to
	annotateForecast(out, s.currentDay(), int(number(out, "unconfirmed_recurring")))
	// This future comparison is not an allowance for spending today.
	out["safe_to_spend"], out["spending_available"] = float64(0), false
	out["spending_restrictions"] = append(stringsList(out["spending_restrictions"]), "scenario_window")
	return out
}
func (s *Service) gapResult(ctx context.Context, op, uid, cid string, gap, out Doc, res forecast.Result, b Doc) (Result, error) {
	// IDs must identify the actual recommendation, including its horizon/model
	// output. Persisting another forecast must never reuse an old funding amount.
	snapshot := sha256.Sum256(store.JSON(out))
	forecastKey := fmt.Sprintf("%s:revision:%d:%x", text(gap, "id"), res.DataRevision, snapshot)
	events, e := s.eventRows(ctx, uid, cid)
	if e != nil {
		return Result{}, e
	}
	actions := []Doc{}
	causes := docs(gap["causes"])
	now := today()
	if s.Now != nil {
		now = domain.Day(s.Now().UTC())
	}
	statementDate, err := day(text(out, "as_of"))
	if err != nil {
		return Result{}, err
	}
	age := int(now.Sub(statementDate).Hours() / 24)
	if age > 7 || age < 0 {
		gap["actions"] = actions
		return ok(gap)
	}
	actions = cashflowCandidates(cid, forecastKey, gap, res, events)
	company, e := s.DB.GetCompany(ctx, uid, cid)
	if e != nil {
		return Result{}, e
	}
	for _, a := range actions {
		a["data_revision"] = res.DataRevision
		changed := res.Clone()
		if text(a, "kind") == "overdraft" {
			dt, _ := day(text(a, "date"))
			changed.Deterministic = append(changed.Deterministic, forecast.ComponentFlow{Date: dt, Key: "overdraft", Amount: domain.Money(number(a, "amount"))})
			e = changed.Recompute()
		} else {
			changed, e = s.applySteps(ctx, uid, cid, res, events, docs(a["steps"]))
		}
		if e != nil {
			return Result{}, e
		}
		a["effect"] = cashflowEffect(res, changed, company.Reserve, cashflowProbabilityReliable(out))
		if old, e := s.DB.ProductGet(ctx, uid, "action", text(a, "id")); e == nil {
			a["applied"] = old["applied"]
			if text(old, "explanation_source") == "llm" {
				a["explanation"], a["explanation_source"] = old["explanation"], "llm"
			}
		} else if !platform.IsStatus(e, 404) {
			return Result{}, e
		}
	}
	rankCashflowActions(actions)
	if op != "simulateGap" {
		s.explainCashflowActions(ctx, actions)
	}
	for _, a := range actions {
		if _, e = s.DB.ProductSave(ctx, uid, cid, "action", text(a, "id"), a, true); e != nil {
			return Result{}, e
		}
	}
	if op == "simulateGap" {
		values, yes := b["action_ids"].([]any)
		if !yes || len(values) == 0 || len(values) > 20 {
			return Result{}, bad("Укажите от 1 до 20 action_ids")
		}
		ids := map[string]bool{}
		for _, v := range values {
			id, ok := v.(string)
			if !ok {
				return Result{}, bad("action_ids должен содержать строки")
			}
			ids[id] = true
		}
		changed := res.Clone()
		for _, a := range actions {
			if !ids[text(a, "id")] {
				continue
			}
			delete(ids, text(a, "id"))
			if text(a, "kind") == "overdraft" {
				dt, _ := day(text(a, "date"))
				changed.Deterministic = append(changed.Deterministic, forecast.ComponentFlow{Date: dt, Key: "overdraft", Amount: domain.Money(number(a, "amount"))})
			} else {
				changed, e = s.applySteps(ctx, uid, cid, changed, events, docs(a["steps"]))
				if e != nil {
					return Result{}, e
				}
			}
		}
		if len(ids) > 0 {
			return Result{}, platform.ErrNotFound
		}
		if e = changed.Recompute(); e != nil {
			return Result{}, e
		}
		points := []Doc{}
		p10, p50, p90 := changed.Quantile(.1), changed.Quantile(.5), changed.Quantile(.9)
		for i, dt := range changed.Dates {
			points = append(points, Doc{"date": dt.Format(domain.DateLayout), "p10": p10[i], "p50": p50[i], "p90": p90[i], "is_workday": isWorkday(dt)})
		}
		return ok(Doc{"points": points, "gaps": s.gapDocuments(changed, company.Reserve)})
	}
	public := []Doc{}
	for _, a := range actions {
		public = append(public, Doc{"id": a["id"], "kind": a["kind"], "title": a["title"], "description": a["description"], "cost": a["cost"], "cost_known": a["cost_known"], "date": a["date"], "amount": a["amount"], "effect": a["effect"], "draft_message": a["draft_message"], "refs": a["refs"], "conditions": a["conditions"], "explanation": a["explanation"], "explanation_source": a["explanation_source"], "original_date": a["original_date"], "deferred_beyond_horizon": a["deferred_beyond_horizon"]})
	}
	gap["causes"], gap["actions"] = causes, public
	return ok(gap)
}
func (s *Service) applyAction(ctx context.Context, uid, id string) (Result, error) {
	d, e := s.DB.ProductGet(ctx, uid, "action", id)
	if e != nil {
		return Result{}, e
	}
	cid := text(d, "company_id")
	if flag(d, "applied") {
		return ok(Doc{"applied": true, "result_ref": d["result_ref"]})
	}
	tx, e := s.DB.Pool.Begin(ctx)
	if e != nil {
		return Result{}, e
	}
	defer tx.Rollback(ctx)
	var revision int64
	if e = tx.QueryRow(ctx, "SELECT c.data_revision FROM companies c JOIN memberships m ON m.company_id=c.id WHERE c.id=$1 AND m.user_id=$2 AND m.role='owner' FOR UPDATE OF c", cid, uid).Scan(&revision); e != nil {
		return Result{}, platform.ErrNotFound
	}
	var data []byte
	if e = tx.QueryRow(ctx, "SELECT data FROM product_documents WHERE id=$1 AND kind='action' FOR UPDATE", id).Scan(&data); e != nil {
		return Result{}, e
	}
	current := store.Decode(data)
	if flag(current, "applied") {
		return ok(Doc{"applied": true, "result_ref": current["result_ref"]})
	}
	version, recorded := current["data_revision"].(float64)
	if !recorded || int64(version) != revision {
		return Result{}, platform.Fail(409, "stale_action", "Данные изменились. Обновите прогноз и выберите рекомендацию заново.")
	}
	d = current
	var ref string
	switch text(d, "kind") {
	case "overdraft":
		ref = idFor(cid, "applied:"+id)
		_, e = tx.Exec(ctx, `INSERT INTO planned_events(id,company_id,source_kind,event_date,amount,direction,title,category,probability,status,extra) VALUES($1,$2,'manual',$3,$4,'in','Плановое привлечение средств','owner_loan',1,'expected','{"additional":true}') ON CONFLICT(id) DO NOTHING`, ref, cid, text(d, "date"), number(d, "amount"))
	case "shift_supplier_payment", "accelerate_receivable":
		steps := docs(d["steps"])
		if len(steps) != 1 {
			return Result{}, bad("Некорректное действие")
		}
		ref = text(steps[0], "event_id")
		tag, err := tx.Exec(ctx, "UPDATE planned_events SET event_date=$3::text::date,extra=extra||jsonb_build_object('date',$3::text,'user_override',true,'_revision',COALESCE((extra->>'_revision')::int,0)+1) WHERE id=$1 AND company_id=$2 AND status='expected' AND source_kind IN ('manual','recurring','invoice')", ref, cid, text(steps[0], "date"))
		e = err
		if e == nil && tag.RowsAffected() == 0 {
			return Result{}, platform.ErrNotFound
		}
		if e == nil {
			// Invoice calendar entries are projections: update their source too,
			// so reconciliation cannot restore the previous expected date.
			_, e = tx.Exec(ctx, `UPDATE product_documents d SET data=d.data||jsonb_build_object('expected_pay_at',$3::text,'_revision',COALESCE((d.data->>'_revision')::int,0)+1),updated_at=now() FROM planned_events p WHERE p.id=$1 AND p.company_id=$2 AND p.source_kind='invoice' AND d.id::text=p.extra->>'document_id' AND d.company_id=$2 AND d.kind='invoice'`, ref, cid, text(steps[0], "date"))
		}
	default:
		return Result{}, bad("Действие не поддерживается")
	}
	if e != nil {
		return Result{}, e
	}
	resultRef := "/v1/companies/" + cid + "/forecast"
	_, e = tx.Exec(ctx, "UPDATE product_documents SET data=data||jsonb_build_object('applied',true,'result_ref',$2::text,'event_id',$3::text),updated_at=now() WHERE id=$1", id, resultRef, ref)
	if e != nil {
		return Result{}, e
	}
	_, e = tx.Exec(ctx, "UPDATE companies SET data_revision=data_revision+1 WHERE id=$1", cid)
	if e != nil {
		return Result{}, e
	}
	if _, e = tx.Exec(ctx, `INSERT INTO product_jobs(actor_id,company_id,kind) VALUES($1,$2,'recompute') ON CONFLICT(company_id) WHERE kind='recompute' AND status='queued' DO NOTHING`, uid, cid); e != nil {
		return Result{}, e
	}
	if _, e = tx.Exec(ctx, "INSERT INTO audit_log(user_id,company_id,action,detail) VALUES($1,$2,'apply_action',$3)", uid, cid, string(store.JSON(Doc{"action_id": id, "event_id": ref}))); e != nil {
		return Result{}, e
	}
	if e = tx.Commit(ctx); e != nil {
		return Result{}, e
	}
	return ok(Doc{"applied": true, "result_ref": resultRef})
}
