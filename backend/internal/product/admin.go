package product

import (
	"context"
	"encoding/csv"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

func (s *Service) reportFile(name string) []byte {
	dir := s.ReportsDir
	if dir == "" {
		dir = "../ml/reports/metrics"
	}
	f, e := os.Open(filepath.Join(dir, name))
	if e != nil {
		return nil
	}
	defer f.Close()
	b, _ := io.ReadAll(io.LimitReader(f, 8*1024*1024))
	return b
}
func (s *Service) ModelQuality() []Doc {
	rows, e := csv.NewReader(strings.NewReader(string(s.reportFile("final_audit.summary.csv")))).ReadAll()
	if e != nil || len(rows) < 2 {
		return []Doc{}
	}
	header := map[string]int{}
	for i, h := range rows[0] {
		header[h] = i
	}
	out := []Doc{}
	for _, row := range rows[1:] {
		val := func(key string) string {
			i, yes := header[key]
			if !yes || i >= len(row) {
				return ""
			}
			return row[i]
		}
		numeric := func(key string) any {
			n, e := strconv.ParseFloat(val(key), 64)
			if e != nil {
				return nil
			}
			return n
		}
		if val("companies") != "all" {
			continue
		} // One row per model; unseen cohort is a separate report, not another model.
		series := []Doc{}
		for _, h := range []string{"7", "14", "30"} {
			series = append(series, Doc{"horizon": h, "wape": numeric("wape_" + h)})
		}
		out = append(out, Doc{"name": val("model"), "wape_7": numeric("wape_7"), "wape_14": numeric("wape_14"), "wape_30": numeric("wape_30"), "coverage": numeric("coverage"), "gap_recall": numeric("gap_recall"), "gap_precision": numeric("gap_precision"), "gap_alerts": numeric("gap_alerts"), "gap_false_alerts": numeric("gap_false_alerts"), "gap_events": numeric("gap_events"), "new_gap_events": numeric("new_gap_events"), "runs": numeric("runs"), "gap_brier": numeric("gap_brier"), "gap_auc": numeric("gap_auc"), "gap_lead_days": numeric("gap_lead_days"), "business_path_wape": numeric("business_path_wape"), "description": "Зафиксированная внутренняя оценка на синтетических компаниях; не независимая проверка на реальных выписках", "source": "ml/reports/metrics/final_audit.summary.csv", "limitations": []string{"synthetic_previously_inspected_data", "nine_gap_events_four_new_gaps", "false_alerts_remain"}, "series": series})
	}
	return out
}
func (s *Service) queryDocs(ctx context.Context, query string, args ...any) ([]Doc, error) {
	rows, e := s.DB.Pool.Query(ctx, query, args...)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []Doc{}
	for rows.Next() {
		var b []byte
		if e = rows.Scan(&b); e != nil {
			return nil, e
		}
		out = append(out, store.Decode(b))
	}
	return out, rows.Err()
}
func (s *Service) admin(ctx context.Context, op string, p platform.Principal, r *http.Request, b Doc) (Result, error) {
	if p.User.Role != "admin" {
		return Result{}, platform.Fail(403, "forbidden", "Нужны права администратора")
	}
	uid := p.User.ID
	q := r.URL.Query()
	switch op {
	case "getAdminOverview":
		rows, e := s.queryDocs(ctx, `SELECT jsonb_build_object('companies',(SELECT count(*) FROM companies),'users',(SELECT count(*) FROM users),'new_week',(SELECT count(*) FROM users WHERE created_at>now()-interval '7 days'),'syncs_ok_24h',(SELECT count(*) FROM product_jobs WHERE kind='sync' AND status='done' AND finished_at>now()-interval '24 hours'),'syncs_failed_24h',(SELECT count(*) FROM product_jobs WHERE kind='sync' AND status='failed' AND finished_at>now()-interval '24 hours'),'open_signals',(SELECT count(*) FROM product_documents WHERE kind='signal' AND data->>'status'<>'closed'),'companies_at_risk_share',(SELECT CASE WHEN count(*)=0 THEN NULL ELSE count(*) FILTER(WHERE payload->>'status'='danger')::float8/count(*) END FROM (SELECT DISTINCT ON(company_id) payload FROM forecast_runs ORDER BY company_id,created_at DESC) r))`)
		if e != nil {
			return Result{}, e
		}
		series, e := s.queryDocs(ctx, `SELECT jsonb_build_object('date',d::date,'users',(SELECT count(*) FROM users u WHERE u.created_at::date=d::date),'companies',(SELECT count(*) FROM companies c WHERE c.created_at::date=d::date)) FROM generate_series(current_date-29,current_date,interval '1 day') d`)
		if e != nil {
			return Result{}, e
		}
		attention, e := s.queryDocs(ctx, `SELECT jsonb_build_object('kind','source_error','title','Источник требует внимания','ref',id) FROM sources WHERE status='error' LIMIT 20`)
		if e != nil {
			return Result{}, e
		}
		return ok(Doc{"counters": rows[0], "series": series, "attention": attention})
	case "listAdminUsers":
		rows, e := s.queryDocs(ctx, `SELECT jsonb_build_object('id',u.id,'email',u.email,'created_at',u.created_at,'last_login_at',u.last_login_at,'companies_count',(SELECT count(*) FROM memberships WHERE user_id=u.id),'status',u.status) FROM users u WHERE ($1='' OR u.email ILIKE '%'||$1||'%') AND ($2='' OR u.status=$2)`, q.Get("q"), q.Get("status"))
		if e != nil {
			return Result{}, e
		}
		result, e := page(rows, r)
		return Result{Status: 200, Body: result}, e
	case "updateAdminUser":
		if e := fields(b, "status reason"); e != nil {
			return Result{}, e
		}
		if !in(text(b, "status"), "active blocked") || text(b, "reason") == "" || len(text(b, "reason")) > 1000 {
			return Result{}, bad("Укажите status и reason")
		}
		id := r.PathValue("userId")
		tx, e := s.DB.Pool.Begin(ctx)
		if e != nil {
			return Result{}, e
		}
		defer tx.Rollback(ctx)
		tag, e := tx.Exec(ctx, "UPDATE users SET status=$2 WHERE id=$1", id, text(b, "status"))
		if e != nil {
			return Result{}, e
		}
		if tag.RowsAffected() == 0 {
			return Result{}, platform.ErrNotFound
		}
		if text(b, "status") == "blocked" {
			if _, e = tx.Exec(ctx, "UPDATE auth_sessions SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", id); e != nil {
				return Result{}, e
			}
		}
		if _, e = tx.Exec(ctx, "INSERT INTO audit_log(user_id,action,detail) VALUES($1,'update_user_status',$2)", uid, string(store.JSON(Doc{"target_user_id": id, "status": b["status"], "reason": b["reason"]}))); e != nil {
			return Result{}, e
		}
		if e = tx.Commit(ctx); e != nil {
			return Result{}, e
		}
		return ok(Doc{"id": id, "status": b["status"]})
	case "listAdminCompanies":
		rows, e := s.queryDocs(ctx, `SELECT jsonb_build_object('id',c.id,'name',c.name,'inn',c.inn,'industry',c.industry,'owner_email',(SELECT u.email FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.company_id=c.id AND m.role='owner' LIMIT 1),'sources_count',(SELECT count(*) FROM sources WHERE company_id=c.id),'data_as_of',(SELECT max(op_date) FROM operations WHERE company_id=c.id),'gap_probability',(SELECT (gaps->0->>'probability')::float8 FROM (SELECT payload->'gaps' AS gaps FROM forecast_runs WHERE company_id=c.id ORDER BY created_at DESC LIMIT 1) r)) FROM companies c WHERE ($1='' OR c.name ILIKE '%'||$1||'%' OR c.inn ILIKE '%'||$1||'%') AND ($2='' OR c.industry=$2)`, q.Get("q"), q.Get("industry"))
		if e != nil {
			return Result{}, e
		}
		if v := q.Get("risk"); v != "" {
			filtered := []Doc{}
			for _, d := range rows {
				if v == "danger" && number(d, "gap_probability") >= .5 || v == "warning" && number(d, "gap_probability") > 0 && number(d, "gap_probability") < .5 || v == "ok" && d["gap_probability"] != nil && number(d, "gap_probability") == 0 {
					filtered = append(filtered, d)
				}
			}
			rows = filtered
		}
		result, e := page(rows, r)
		return Result{Status: 200, Body: result}, e
	case "getAdminCompany":
		cid := r.PathValue("companyId")
		rows, e := s.queryDocs(ctx, "SELECT to_jsonb(c)||jsonb_build_object('data_as_of',(SELECT max(op_date)::timestamptz FROM operations WHERE company_id=c.id)) FROM companies c WHERE id=$1", cid)
		if e != nil {
			return Result{}, e
		}
		if len(rows) == 0 {
			return Result{}, platform.ErrNotFound
		}
		ip, _, _ := net.SplitHostPort(r.RemoteAddr)
		agent := r.UserAgent()
		if len(agent) > 256 {
			agent = agent[:256]
		}
		if e = s.DB.Audit(ctx, uid, cid, "admin_view_company", Doc{"ip": ip, "user_agent": agent}); e != nil {
			return Result{}, e
		}
		company := rows[0]
		sources, e := s.queryDocs(ctx, "SELECT (to_jsonb(s)-'config'-'config_secret'-'extra')||jsonb_build_object('records',(SELECT count(*) FROM operations WHERE source_id=s.id)) FROM sources s WHERE company_id=$1", cid)
		if e != nil {
			return Result{}, e
		}
		stats, e := s.queryDocs(ctx, "SELECT jsonb_build_object('count',count(*),'from',min(op_date),'to',max(op_date),'internal_count',count(*) FILTER(WHERE is_internal)) FROM operations WHERE company_id=$1", cid)
		if e != nil {
			return Result{}, e
		}
		forecasts, e := s.queryDocs(ctx, "SELECT payload FROM forecast_runs WHERE company_id=$1 ORDER BY created_at DESC LIMIT 1", cid)
		if e != nil {
			return Result{}, e
		}
		signals, e := s.queryDocs(ctx, "SELECT data||jsonb_build_object('id',id,'created_at',created_at) FROM product_documents WHERE kind='signal' AND company_id=$1 ORDER BY created_at DESC LIMIT 100", cid)
		if e != nil {
			return Result{}, e
		}
		var latest any
		if len(forecasts) > 0 {
			latest = forecasts[0]
		}
		return ok(Doc{"company": company, "sources": sources, "operations_stats": stats[0], "forecast": latest, "signals": signals})
	case "listAdminIntegrations":
		rows, e := s.queryDocs(ctx, `SELECT (to_jsonb(s)-'config'-'config_secret'-'extra')||jsonb_build_object('company',jsonb_build_object('id',c.id,'name',c.name),'records',(SELECT count(*) FROM operations WHERE source_id=s.id)) FROM sources s JOIN companies c ON c.id=s.company_id WHERE ($1='' OR s.kind=$1) AND ($2='' OR s.status=$2)`, q.Get("kind"), q.Get("status"))
		if e != nil {
			return Result{}, e
		}
		result, e := page(rows, r)
		return Result{Status: 200, Body: result}, e
	case "getAdminIntegrationStats":
		rows, e := s.queryDocs(ctx, `SELECT jsonb_build_object('kind',s.kind,'connected',count(*),'error_share',count(*) FILTER(WHERE status='error')::float8/count(*),'avg_sync_seconds',(SELECT avg(extract(epoch FROM j.finished_at-j.created_at)) FROM product_jobs j WHERE j.kind='sync' AND j.status='done' AND j.payload->>'source_id' IN(SELECT id::text FROM sources WHERE kind=s.kind))) FROM sources s GROUP BY s.kind`)
		if e != nil {
			return Result{}, e
		}
		return ok(Doc{"items": rows})
	case "retryAdminIntegration":
		id := r.PathValue("sourceId")
		var cid, owner, kind string
		var enabled bool
		e := s.DB.Pool.QueryRow(ctx, "SELECT s.company_id::text,m.user_id::text,s.kind,s.enabled FROM sources s JOIN memberships m ON m.company_id=s.company_id WHERE s.id=$1 AND m.role='owner' LIMIT 1", id).Scan(&cid, &owner, &kind, &enabled)
		if e != nil {
			return Result{}, platform.ErrNotFound
		}
		if !in(kind, "onec_odata gsheets fns wb ozon bank_api tax_api") {
			return Result{}, platform.Fail(409, "source_not_syncable", "Файловый источник обновляется повторной загрузкой выписки")
		}
		if !enabled {
			return Result{}, platform.Fail(409, "source_disabled", "Сначала включите источник")
		}
		j, e := s.DB.ProductJob(ctx, owner, cid, "sync", Doc{"source_id": id, "requested_by_admin": uid})
		if e != nil {
			return Result{}, e
		}
		if e = s.DB.Audit(ctx, uid, cid, "admin_retry_source", Doc{"source_id": id}); e != nil {
			return Result{}, e
		}
		return Result{Status: 202, Body: j}, nil
	case "listAdminModels":
		models := s.ModelQuality()
		for _, model := range models {
			model["is_default"] = text(model, "name") == "auto"
			model["trained_at"], model["companies"] = nil, nil
			model["metrics"] = Doc{"wape_7": model["wape_7"], "wape_14": model["wape_14"], "wape_30": model["wape_30"], "coverage": model["coverage"], "gap_brier": model["gap_brier"], "gap_auc": model["gap_auc"], "gap_lead_days": model["gap_lead_days"]}
		}
		return ok(models)
	case "getModelDrift":
		rows, e := s.queryDocs(ctx, `SELECT jsonb_build_object('week',date_trunc('week',p.point_date)::date,'mean_absolute_error',avg(abs(p.p50-o.balance_eod))::float8,'samples',count(*)) FROM forecast_points p JOIN forecast_runs f ON f.id=p.run_id JOIN (SELECT company_id,op_date,max(balance_eod) AS balance_eod FROM operations WHERE balance_eod IS NOT NULL GROUP BY company_id,op_date) o ON o.company_id=f.company_id AND o.op_date=p.point_date WHERE p.point_date>f.as_of AND p.point_date>=current_date-28 GROUP BY date_trunc('week',p.point_date)`)
		if e != nil {
			return Result{}, e
		}
		return ok(Doc{"items": rows, "retrain_threshold": nil, "needs_retraining": nil, "description": "Ошибка рассчитана только по сохранённым прогнозам и наблюдаемым остаткам; порог переобучения не задан"})
	case "retrainModel":
		name := r.PathValue("name")
		if !in(name, "auto ensemble gbm_global seasonal_naive classifier") {
			return Result{}, platform.ErrNotFound
		}
		if s.TrainingURL == "" {
			return Result{}, platform.Fail(503, "training_not_configured", "Нужен сервис переобучения TRAINING_URL; gRPC сервиса прогнозов не предоставляет эту операцию")
		}
		j, e := s.DB.ProductJob(ctx, uid, "", "retrain", Doc{"model": name})
		return Result{Status: 202, Body: j}, e
	case "getClassifierQuality":
		raw := store.Decode(s.reportFile("classifier_dropout_evaluation.json"))
		hold, _ := raw["holdout"].(map[string]any)
		model, _ := hold["model"].(map[string]any)
		var corrections int
		e := s.DB.Pool.QueryRow(ctx, "SELECT count(*) FROM category_corrections WHERE created_at>now()-interval '7 days'").Scan(&corrections)
		if e != nil {
			return Result{}, e
		}
		byCategory := []Doc{}
		if scores, yes := model["f1"].(map[string]any); yes {
			for category, score := range scores {
				byCategory = append(byCategory, Doc{"category": category, "f1": score, "precision": nil, "recall": nil})
			}
			sort.Slice(byCategory, func(i, j int) bool { return text(byCategory[i], "category") < text(byCategory[j], "category") })
		}
		return ok(Doc{"accuracy": model["accuracy"], "macro_f1": model["macro_f1"], "by_category": byCategory, "user_corrections_week": corrections, "retrained_at": nil, "source": "ml/reports/metrics/classifier_dropout_evaluation.json", "limitations": []string{"weak_labels_not_independent_human_gold", "precision_recall_not_published"}})
	case "listSignals":
		rows, e := s.queryDocs(ctx, `SELECT d.data||jsonb_build_object('id',d.id,'created_at',d.created_at,'company',jsonb_build_object('id',c.id,'name',c.name)) FROM product_documents d JOIN companies c ON c.id=d.company_id WHERE d.kind='signal' AND ($1='' OR d.data->>'status'=$1) AND ($2='' OR d.data->>'kind'=$2) AND ($3='' OR d.data->>'severity'=$3) AND ($4='' OR d.company_id::text=$4)`, q.Get("status"), q.Get("kind"), q.Get("severity"), q.Get("company_id"))
		if e != nil {
			return Result{}, e
		}
		result, e := page(rows, r)
		return Result{Status: 200, Body: result}, e
	case "getSignal", "updateSignal":
		id := r.PathValue("signalId")
		rows, e := s.queryDocs(ctx, `SELECT d.data||jsonb_build_object('id',d.id,'created_at',d.created_at,'company',jsonb_build_object('id',c.id,'name',c.name)) FROM product_documents d JOIN companies c ON c.id=d.company_id WHERE d.id=$1 AND d.kind='signal'`, id)
		if e != nil {
			return Result{}, e
		}
		if len(rows) == 0 {
			return Result{}, platform.ErrNotFound
		}
		d := rows[0]
		if op == "getSignal" {
			company, _ := d["company"].(map[string]any)
			operations, e := s.queryDocs(ctx, "SELECT o.extra||(to_jsonb(o)-'extra') FROM operations o WHERE company_id=$1 AND id=$2", company["id"], text(d, "operation_id"))
			if e != nil {
				return Result{}, e
			}
			views := []Doc{}
			for _, operation := range operations {
				views = append(views, view("operation", operation))
				d["counterparty"] = cpRef(text(operation, "company_id"), operation)
			}
			if len(views) == 0 {
				d["counterparty"] = nil
			}
			d["operations"] = views
			history, e := s.queryDocs(ctx, "SELECT data||jsonb_build_object('id',id,'created_at',created_at,'company',$2::jsonb) FROM product_documents WHERE kind='signal' AND company_id=$1 ORDER BY created_at DESC LIMIT 50", company["id"], string(store.JSON(company)))
			if e != nil {
				return Result{}, e
			}
			d["company_history"] = history
			return ok(d)
		}
		if e = fields(b, "status resolution comment"); e != nil {
			return Result{}, e
		}
		if !in(text(b, "status"), "new in_progress closed") {
			return Result{}, bad("Неизвестный статус сигнала")
		}
		if v := text(b, "resolution"); v != "" && !in(v, "false_positive confirmed escalated") {
			return Result{}, bad("Неизвестное решение")
		}
		if text(b, "status") == "closed" && text(b, "resolution") == "" {
			return Result{}, bad("Для закрытия укажите resolution")
		}
		if len(text(b, "comment")) > 2000 {
			return Result{}, bad("Слишком длинный комментарий")
		}
		for k, v := range b {
			d[k] = v
		}
		if _, e = s.DB.Pool.Exec(ctx, "UPDATE product_documents SET data=data||$2::jsonb,updated_at=now() WHERE id=$1", id, string(store.JSON(b))); e != nil {
			return Result{}, e
		}
		if e = s.DB.Audit(ctx, uid, "", "admin_update_signal", Doc{"signal_id": id, "status": b["status"]}); e != nil {
			return Result{}, e
		}
		return ok(d)
	case "getSignalStats":
		rows, e := s.queryDocs(ctx, `SELECT jsonb_build_object('kind',data->>'kind','count',count(*),'confirmed_share',count(*) FILTER(WHERE data->>'resolution'='confirmed')::float8/count(*)) FROM product_documents WHERE kind='signal' AND created_at>now()-interval '30 days' GROUP BY data->>'kind'`)
		if e != nil {
			return Result{}, e
		}
		return ok(Doc{"items": rows})
	case "listAudit":
		rows, e := s.queryDocs(ctx, `SELECT jsonb_build_object('id',a.id::text,'at',a.created_at,'actor',jsonb_build_object('id',u.id,'email',u.email,'role',u.role),'company_id',a.company_id,'action',a.action,'ip',a.detail->>'ip','user_agent',a.detail->>'user_agent') FROM audit_log a LEFT JOIN users u ON u.id=a.user_id WHERE ($1='' OR a.user_id::text=$1) AND ($2='' OR a.company_id::text=$2) AND ($3='' OR a.action=$3) AND ($4='' OR a.created_at::date>=$4::date) AND ($5='' OR a.created_at::date<=$5::date)`, q.Get("user_id"), q.Get("company_id"), q.Get("action"), q.Get("from"), q.Get("to"))
		if e != nil {
			return Result{}, e
		}
		result, e := page(rows, r)
		return Result{Status: 200, Body: result}, e
	}
	return Result{}, bad("Неизвестная административная операция")
}
