// Package product implements the financial API on the existing Go domain/ML pipeline.
package product

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"math"
	"mime/multipart"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/google/uuid"
)

type Doc = store.Doc
type Result struct {
	Status         int
	Body           any
	Data           []byte
	Filename, MIME string
}
type Service struct {
	IntegrationSandbox                                  bool
	FNSHubURL, FNSHubToken, FNSHubCompany               string
	DB                                                  *store.Postgres
	ML                                                  forecast.StochasticForecaster
	Fallback                                            forecast.StochasticForecaster
	Categorizer                                         categorize.Categorizer
	EncryptionKey                                       []byte
	AllowedSourceHosts                                  []string
	DaDataToken, ReportsDir, TrainingURL, TrainingToken string
	HTTP                                                *http.Client
}

func ok(v any) (Result, error)    { return Result{Status: 200, Body: v}, nil }
func bad(message string) error    { return platform.Fail(400, "invalid_request", message) }
func text(d Doc, k string) string { v, _ := d[k].(string); return v }
func number(d Doc, k string) float64 {
	switch n := d[k].(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case int64:
		return float64(n)
	case json.Number:
		v, _ := n.Float64()
		return v
	}
	return 0
}
func flag(d Doc, k string) bool { v, _ := d[k].(bool); return v }
func docs(v any) []Doc {
	out := []Doc{}
	switch a := v.(type) {
	case []any:
		for _, v := range a {
			if d, ok := v.(map[string]any); ok {
				out = append(out, Doc(d))
			}
		}
	case []Doc:
		return a
	}
	return out
}
func day(v string) (time.Time, error) {
	t, e := time.Parse(domain.DateLayout, v)
	if e != nil {
		return t, bad("Дата должна иметь формат YYYY-MM-DD")
	}
	return t, nil
}
func today() time.Time { return domain.Day(time.Now().UTC()) }
func date(v any) string {
	if v == nil {
		return ""
	}
	s, _ := v.(string)
	if len(s) > 10 {
		return s[:10]
	}
	return s
}
func money(v float64) float64 { return math.Round(v*100) / 100 }
func knownCategory(s string) bool {
	for _, c := range domain.AllCategories {
		if string(c) == s {
			return true
		}
	}
	return false
}
func idFor(cid, key string) string {
	return uuid.NewSHA1(uuid.NameSpaceOID, []byte(cid+":"+key)).String()
}
func cpKey(d Doc) string {
	if v := text(d, "counterparty_inn"); v != "" {
		return "inn:" + v
	}
	return "name:" + strings.ToLower(strings.Join(strings.Fields(text(d, "counterparty_name")), " "))
}
func cpRef(cid string, d Doc) Doc {
	key := cpKey(d)
	var id any
	if key != "name:" {
		id = idFor(cid, key)
	}
	return Doc{"id": id, "name": text(d, "counterparty_name")}
}
func fields(d Doc, allowed string) error {
	for k := range d {
		if !strings.Contains(" "+allowed+" ", " "+k+" ") {
			return bad("Неизвестное поле: " + k)
		}
	}
	return nil
}
func rangeDates(r *http.Request) (string, string, error) {
	from, to := r.URL.Query().Get("from"), r.URL.Query().Get("to")
	if from != "" {
		if _, e := day(from); e != nil {
			return "", "", e
		}
	}
	if to != "" {
		if _, e := day(to); e != nil {
			return "", "", e
		}
	}
	if from != "" && to != "" && from > to {
		return "", "", bad("Начало периода позже окончания")
	}
	return from, to, nil
}
func filterDates(rows []Doc, from, to, key string) []Doc {
	out := []Doc{}
	for _, d := range rows {
		v := date(d[key])
		if (from == "" || v >= from) && (to == "" || v <= to) {
			out = append(out, d)
		}
	}
	return out
}
func page(rows []Doc, r *http.Request) (Doc, error) {
	limit := 100
	if raw := r.URL.Query().Get("limit"); raw != "" {
		n, e := strconv.Atoi(raw)
		if e != nil || n < 1 || n > 1000 {
			return nil, bad("limit должен быть от 1 до 1000")
		}
		limit = n
	}
	after := ""
	if cur := r.URL.Query().Get("cursor"); cur != "" {
		b, e := base64.RawURLEncoding.DecodeString(cur)
		if e != nil || len(b) > 256 {
			return nil, bad("Некорректный cursor")
		}
		after = string(b)
	}
	sort.Slice(rows, func(i, j int) bool { return text(rows[i], "id") < text(rows[j], "id") })
	start := 0
	for start < len(rows) && text(rows[start], "id") <= after {
		start++
	}
	end := start + limit
	if end > len(rows) {
		end = len(rows)
	}
	var next any
	if end < len(rows) {
		next = base64.RawURLEncoding.EncodeToString([]byte(text(rows[end-1], "id")))
	}
	return Doc{"items": rows[start:end], "next_cursor": next}, nil
}
func view(kind string, d Doc) Doc {
	cid := text(d, "company_id")
	out := Doc{}
	copyKeys := func(keys string) {
		for _, k := range strings.Fields(keys) {
			out[k] = d[k]
		}
	}
	switch kind {
	case "operation":
		copyKeys("id amount direction purpose category category_method is_internal")
		out["date"] = date(d["op_date"])
		out["counterparty"] = cpRef(cid, d)
		out["source"] = operationSource(d)
		if out["purpose"] == nil {
			out["purpose"] = ""
		}
	case "event":
		copyKeys("id amount direction title category probability status")
		out["additional"] = flag(d, "additional")
		for _, key := range []string{"linked_event_id", "linked_sources", "link_status"} {
			if value, ok := d[key]; ok {
				out[key] = value
			}
		}
		if in(text(d, "source_kind"), "bank_api tax_api") {
			copyKeys("source_id external_id obligation_kind tax_kind period year data_mode")
		}
		if text(d, "source_kind") == "onec_odata" {
			copyKeys("source_id external_id due_date total_kopecks paid_kopecks remaining_kopecks forecast_eligible link_status data_mode payment_status version")
		}
		out["date"] = date(d["event_date"])
		out["source"] = d["source_kind"]
		out["counterparty"] = cpRef(cid, d)
		out["editable"] = text(d, "source_kind") == "manual" || text(d, "source_kind") == "recurring"
		if out["category"] == nil {
			out["category"] = "other"
		}
	case "recurring":
		copyKeys("id title category direction period day_of_month amount amount_spread confirmed active")
		out["next_date"] = date(d["next_date"])
		out["counterparty"] = cpRef(cid, d)
		out["origin"] = d["origin"]
		if out["origin"] == nil {
			out["origin"] = "detected"
		}
	case "source":
		copyKeys("id kind title status enabled last_synced_at error")
		out["data_mode"] = d["data_mode"]
		if out["title"] == nil {
			out["title"] = ""
		}
		out["records"] = number(d, "records")
	case "scenario":
		copyKeys("id title preset steps created_at")
	case "alert":
		copyKeys("id created_at severity kind title body read")
		out["ref"] = d["ref"]
		if out["ref"] == nil {
			out["ref"] = Doc{"screen": "dashboard", "id": nil}
		}
		if out["body"] == nil {
			out["body"] = ""
		}
	case "invoice":
		copyKeys("id number direction amount paid_amount issued_at due_at expected_pay_at status source additional")
		out["additional"] = flag(d, "additional")
		out["counterparty"] = cpRef(cid, d)
	case "contract":
		copyKeys("id number direction total prepayment deferral_days schedule source additional start_date schedule_mode")
		out["additional"] = flag(d, "additional")
		out["counterparty"] = cpRef(cid, d)
	default:
		for k, v := range d {
			if k != "company_id" && k != "_revision" {
				out[k] = v
			}
		}
	}
	return out
}

var crudOps = map[string][3]string{
	"listEvents": {"event", "list", ""}, "createEvent": {"event", "create", ""}, "updateEvent": {"event", "update", "eventId"}, "deleteEvent": {"event", "delete", "eventId"},
	"listRecurring": {"recurring", "list", ""}, "createRecurring": {"recurring", "create", ""}, "updateRecurring": {"recurring", "update", "patternId"}, "deleteRecurring": {"recurring", "delete", "patternId"},
	"listScenarios": {"scenario", "list", ""}, "createScenario": {"scenario", "create", ""}, "updateScenario": {"scenario", "update", "scenarioId"}, "deleteScenario": {"scenario", "delete", "scenarioId"},
	"listInvoices": {"invoice", "list", ""}, "createInvoice": {"invoice", "create", ""}, "updateInvoice": {"invoice", "update", "invoiceId"}, "deleteInvoice": {"invoice", "delete", "invoiceId"},
	"listContracts": {"contract", "list", ""}, "createContract": {"contract", "create", ""}, "updateContract": {"contract", "update", "contractId"}, "deleteContract": {"contract", "delete", "contractId"},
	"listSources": {"source", "list", ""}, "createSource": {"source", "create", ""}, "updateSource": {"source", "update", "sourceId"}, "deleteSource": {"source", "delete", "sourceId"},
	"updateOperation": {"operation", "update", "operationId"}, "updateAlert": {"alert", "update", "alertId"},
}

func (s *Service) Execute(ctx context.Context, op string, p platform.Principal, r *http.Request, raw map[string]json.RawMessage, upload *multipart.Reader) (Result, error) {
	if op == "getModelQuality" {
		return ok(s.ModelQuality())
	}
	if s.DB == nil {
		return Result{}, platform.Fail(503, "storage_unavailable", "Хранилище не настроено")
	}
	body := Doc{}
	for k, b := range raw {
		var v any
		if e := json.Unmarshal(b, &v); e != nil {
			return Result{}, bad("Некорректный JSON")
		}
		body[k] = v
	}
	uid, cid := p.User.ID, r.PathValue("companyId")
	if strings.HasPrefix(op, "getAdmin") || strings.HasPrefix(op, "listAdmin") || strings.HasPrefix(r.URL.Path, "/v1/admin/") {
		if p.User.Role != "admin" {
			return Result{}, platform.Fail(403, "forbidden", "Нужны права администратора")
		}
		return s.admin(ctx, op, p, r, body)
	}
	if cid != "" {
		if _, e := s.DB.GetCompany(ctx, uid, cid); e != nil {
			return Result{}, e
		}
	}
	if desc, yes := crudOps[op]; yes {
		return s.crud(ctx, uid, cid, desc, r, body)
	}
	switch op {
	case "previewTax", "createTax", "cancelTax":
		return s.taxAction(ctx, op, uid, cid, r, body)
	case "getTaxes":
		return s.taxes(ctx, uid, cid, r)
	case "getCompanyUpdates":
		return s.updates(ctx, uid, cid)
	case "listCategories":
		return ok(Categories())
	case "listOperations", "summarizeOperations", "exportOperations", "recategorizeOperations":
		return s.operations(ctx, op, uid, cid, r, body)
	case "getForecast", "getDashboard", "getForecastDay", "getGap", "previewForecast", "simulateGap", "getCalendar", "getForecastAccuracy", "getRetro", "getPlanFact", "getMissedPlanFact":
		return s.financial(ctx, op, uid, cid, r, body)
	case "listCounterparties", "getCounterparty", "getConcentration":
		return s.counterparties(ctx, op, uid, cid, r)
	case "listScenarioPresets":
		return ok(ScenarioPresets())
	case "previewScenario", "compareScenario", "compareSavedScenario":
		return s.compare(ctx, op, uid, cid, r, body)
	case "parseEvent":
		return s.parseEvent(body)
	case "listAlerts", "readAllAlerts":
		return s.alerts(ctx, op, uid, cid, r)
	case "applyAction":
		return s.applyAction(ctx, uid, r.PathValue("actionId"))
	case "lookupFNS":
		return s.lookup(ctx, uid, r.URL.Query().Get("inn"))
	case "uploadStatement":
		return s.upload(ctx, uid, cid, upload)
	case "previewUpload", "mapUpload":
		return s.uploadMapping(ctx, op, uid, r.PathValue("uploadId"), body)
	case "getSource", "testSource", "syncSource":
		return s.sourceAction(ctx, op, uid, r.PathValue("sourceId"))
	case "listImports":
		list, e := s.DB.ProductList(ctx, uid, cid, "import")
		if e != nil {
			return Result{}, e
		}
		return ok(list)
	case "getImport":
		d, e := s.DB.ProductGet(ctx, uid, "import", r.PathValue("importId"))
		if e != nil {
			return Result{}, e
		}
		return ok(view("import", d))
	case "getJob":
		d, e := s.DB.GetProductJob(ctx, uid, r.PathValue("jobId"), p.User.Role == "admin")
		if e != nil {
			return Result{}, e
		}
		return ok(d)
	case "downloadJob":
		return s.download(ctx, uid, r.PathValue("jobId"))
	case "exportCompany":
		j, e := s.DB.ProductJob(ctx, uid, cid, "export", Doc{})
		return Result{Status: 202, Body: j}, e
	}
	return Result{}, errors.New("product operation is not registered: " + op)
}
func (s *Service) crud(ctx context.Context, uid, cid string, desc [3]string, r *http.Request, body Doc) (Result, error) {
	kind, method, param := desc[0], desc[1], desc[2]
	id := r.PathValue(param)
	if method == "list" {
		if kind == "event" || kind == "recurring" {
			if e := s.projectRecurring(ctx, uid, cid); e != nil {
				return Result{}, e
			}
		}
		rows, e := s.DB.ProductList(ctx, uid, cid, kind)
		if kind == "event" && e == nil {
			rows, e = s.linkPaymentOrders(ctx, uid, cid, rows)
		}
		if e != nil {
			return Result{}, e
		}
		from, to, e := rangeDates(r)
		if e != nil {
			return Result{}, e
		}
		if kind == "event" {
			rows = filterDates(rows, from, to, "event_date")
		}
		out := []Doc{}
		for _, d := range rows {
			if v := r.URL.Query().Get("direction"); v != "" && text(d, "direction") != v {
				continue
			}
			if v := r.URL.Query().Get("status"); v != "" && text(d, "status") != v {
				continue
			}
			out = append(out, view(kind, d))
		}
		return ok(out)
	}
	d := Doc{}
	create := method == "create"
	if !create {
		var e error
		d, e = s.DB.ProductGet(ctx, uid, kind, id)
		if e != nil {
			return Result{}, e
		}
		cid = text(d, "company_id")
	}
	if method == "delete" {
		if kind == "event" && text(d, "source_kind") != "manual" || kind == "recurring" && text(d, "origin") != "manual" {
			return Result{}, platform.Fail(409, "managed_resource", "Удаление доступно только для ручных записей")
		}
		if kind == "source" {
			return s.deleteSource(ctx, uid, cid, id, body)
		}
		if e := s.DB.ProductDelete(ctx, uid, cid, kind, id); e != nil {
			return Result{}, e
		}
		return Result{Status: 204}, nil
	}
	if create {
		id = uuid.NewString()
	}
	if e := validateResource(kind, body, create); e != nil {
		return Result{}, e
	}
	// "Mark paid" is an explicit transition, not a standing instruction to
	// manufacture another payment whenever an already-paid invoice is edited.
	if kind == "invoice" && text(body, "status") == "paid" && (create || text(d, "status") != "paid") {
		amount := d["amount"]
		if value, exists := body["amount"]; exists {
			amount = value
		}
		body["paid_amount"] = amount
	}
	if kind == "source" && !create {
		if patch, yes := body["config"].(map[string]any); yes {
			_, previous, err := s.sourceConfig(ctx, uid, id)
			if err != nil {
				return Result{}, err
			}
			for key, value := range patch {
				previous[key] = value
			}
			body["config"] = map[string]any(previous)
			d["status"], d["error"] = "pending", nil
		}
		if enabled, yes := body["enabled"].(bool); yes && enabled && !flag(d, "enabled") {
			d["status"], d["error"] = "pending", nil
		}
	}
	if kind == "recurring" && !create {
		rememberRecurringBaseline(d)
	}
	for k, v := range body {
		d[k] = v
	}
	if kind == "contract" {
		if _, supplied := body["schedule"]; supplied {
			d["schedule_mode"] = "explicit"
		}
	}
	if !create && kind == "event" && text(d, "source_kind") == "recurring" && len(body) > 0 {
		// An individual installment edited by the user survives pattern edits.
		d["user_override"] = true
	}
	d["id"], d["company_id"] = id, cid
	if e := s.prepare(ctx, uid, cid, kind, d, create); e != nil {
		return Result{}, e
	}
	var sealed []byte
	if kind == "source" {
		if _, yes := body["config"]; yes {
			var e error
			sealed, e = s.seal(store.JSON(body["config"]))
			if e != nil {
				return Result{}, e
			}
			delete(d, "config")
			d["_sealed_config"] = sealed
		}
	}
	saved, e := s.DB.ProductSave(ctx, uid, cid, kind, id, d, create)
	if e != nil {
		return Result{}, e
	}
	code := 200
	if create {
		code = 201
	}
	return Result{Status: code, Body: view(kind, saved)}, nil
}
func validateResource(kind string, b Doc, create bool) error {
	if !create && kind == "source" {
		if _, yes := b["kind"]; yes {
			return bad("Тип существующего источника менять нельзя")
		}
	}
	if kind == "invoice" {
		if v := text(b, "status"); v != "" && !in(v, "open partial paid overdue") {
			return bad("Неизвестный статус счёта")
		}
	}
	allowed := map[string]string{"event": "date amount direction title category counterparty_name counterparty_inn probability status additional", "recurring": "title direction amount period day_of_month counterparty_name counterparty_inn category confirmed active", "scenario": "title steps", "invoice": "number direction amount paid_amount issued_at due_at expected_pay_at status counterparty_name counterparty_inn additional", "contract": "number direction total prepayment deferral_days start_date schedule counterparty_name counterparty_inn additional", "source": "kind title config enabled", "operation": "category", "alert": "read"}[kind]
	if e := fields(b, allowed); e != nil {
		return e
	}
	if len(b) == 0 {
		return bad("Укажите поля записи")
	}
	required := map[string]string{"event": "date amount direction title", "recurring": "title direction amount period", "scenario": "title steps", "invoice": "number direction amount issued_at due_at", "contract": "number direction total", "source": "kind title", "operation": "category", "alert": "read"}
	if create {
		for _, k := range strings.Fields(required[kind]) {
			if v, ok := b[k]; !ok || v == nil {
				return bad("Не заполнено поле: " + k)
			}
		}
	}
	for k, v := range b {
		if v == nil {
			return bad("Поле не может быть null: " + k)
		}
		switch k {
		case "amount", "paid_amount", "total", "prepayment":
			n, ok := v.(float64)
			if !ok || math.IsInf(n, 0) || math.IsNaN(n) || n < 0 || n > 1e13 || math.Abs(n*100-math.Round(n*100)) > 0.001 {
				return bad("Суммы должны быть неотрицательными, с точностью до копейки")
			}
		case "probability":
			n, ok := v.(float64)
			if !ok || n < 0 || n > 1 {
				return bad("Вероятность должна быть от 0 до 1")
			}
		case "day_of_month":
			n, ok := v.(float64)
			if !ok || n != math.Trunc(n) || n < 1 || n > 31 {
				return bad("День месяца должен быть от 1 до 31")
			}
		case "deferral_days":
			n, ok := v.(float64)
			if !ok || n != math.Trunc(n) || n < 0 || n > 3650 {
				return bad("Некорректная отсрочка")
			}
		case "date", "issued_at", "due_at", "expected_pay_at", "start_date":
			s, ok := v.(string)
			if !ok {
				return bad("Некорректная дата")
			}
			if _, e := day(s); e != nil {
				return e
			}
		case "active", "enabled", "confirmed", "read", "additional":
			if _, ok := v.(bool); !ok {
				return bad("Требуется логическое значение: " + k)
			}
		case "steps", "schedule":
			entries, ok := v.([]any)
			if !ok || len(docs(v)) != len(entries) {
				return bad("Требуется список: " + k)
			}
		case "config":
			if _, ok := v.(map[string]any); !ok {
				return bad("config должен быть объектом")
			}
		default:
			s, ok := v.(string)
			if !ok || utf8.RuneCountInString(s) > 1024 || strings.TrimSpace(s) == "" {
				return bad("Некорректное поле: " + k)
			}
		}
	}
	if v := text(b, "category"); v != "" && !knownCategory(v) {
		return bad("Неизвестная категория")
	}
	return nil
}
func (s *Service) prepare(ctx context.Context, uid, cid, kind string, d Doc, create bool) error {
	defaults := func(k string, v any) {
		if _, yes := d[k]; !yes {
			d[k] = v
		}
	}
	switch kind {
	case "event":
		defaults("source", "manual")
		defaults("probability", float64(1))
		defaults("status", "expected")
		defaults("category", "other")
		defaults("counterparty_name", "")
		defaults("additional", true)
		if !create && text(d, "source_kind") != "manual" && text(d, "source_kind") != "recurring" {
			return platform.Fail(409, "managed_resource", "Измените исходный счёт или договор")
		}
		if !in(text(d, "status"), "expected received missed cancelled") {
			return bad("Неизвестный статус события")
		}
	case "recurring":
		defaults("origin", "manual")
		defaults("active", true)
		defaults("confirmed", true)
		defaults("category", "other")
		defaults("counterparty_name", "")
		defaults("amount_spread", float64(0))
		defaults("day_of_month", float64(today().Day()))
		if !in(text(d, "period"), "weekly biweekly monthly quarterly") {
			return bad("Неизвестный период")
		}
		d["next_date"] = nextOccurrence(today().AddDate(0, 0, -1), text(d, "period"), int(number(d, "day_of_month"))).Format(domain.DateLayout)
	case "source":
		if create && in(text(d, "kind"), "wb ozon gsheets fns") {
			if s.IntegrationSandbox {
				d["data_mode"] = "mock"
			} else {
				d["data_mode"] = "live"
			}
		}
		defaults("enabled", true)
		if create && in(text(d, "kind"), "onec_odata gsheets fns wb ozon bank_api tax_api") {
			defaults("status", "pending")
		} else {
			defaults("status", "ok")
		}
		if !flag(d, "enabled") {
			d["status"] = "disabled"
		}
		if !in(text(d, "kind"), "upload onec_bank_file excel gsheets onec_odata fns manual wb ozon bank_api tax_api") {
			return bad("Неизвестный источник")
		}
		if create && in(text(d, "kind"), "gsheets onec_odata wb ozon bank_api tax_api") && d["config"] == nil {
			return bad("Для сетевого источника укажите config")
		}
		if cfg, yes := d["config"].(map[string]any); yes {
			if e := s.validateSourceConfig(ctx, uid, cid, text(d, "kind"), Doc(cfg), false); e != nil {
				return e
			}
		}
	case "scenario":
		if e := validateSteps(docs(d["steps"])); e != nil {
			return e
		}
	case "invoice":
		defaults("additional", true)
		defaults("paid_amount", float64(0))
		defaults("expected_pay_at", d["due_at"])
		defaults("source", "manual")
		defaults("counterparty_name", "")
		if number(d, "paid_amount") > number(d, "amount") {
			return bad("Оплаченная сумма больше суммы счёта")
		}
		if text(d, "issued_at") > text(d, "due_at") {
			return bad("Срок оплаты раньше даты счёта")
		}
		if !in(text(d, "direction"), "issued received") {
			return bad("Направление счёта: issued или received")
		}
		switch {
		case number(d, "paid_amount") >= number(d, "amount"):
			d["status"] = "paid"
		case number(d, "paid_amount") > 0:
			d["status"] = "partial"
		case text(d, "due_at") < today().Format(domain.DateLayout):
			d["status"] = "overdue"
		default:
			d["status"] = "open"
		}
	case "contract":
		defaults("additional", true)
		defaults("prepayment", float64(0))
		defaults("deferral_days", float64(0))
		defaults("source", "manual")
		defaults("counterparty_name", "")
		if !in(text(d, "direction"), "in out") {
			return bad("Направление договора: in или out")
		}
		if number(d, "prepayment") > number(d, "total") {
			return bad("Предоплата больше суммы договора")
		}
		if _, supplied := d["schedule"]; !supplied || text(d, "schedule_mode") == "terms" {
			if e := contractSchedule(d); e != nil {
				return e
			}
		} else {
			d["schedule_mode"] = "explicit"
		}
		sum := float64(0)
		if len(docs(d["schedule"])) > 500 {
			return bad("Слишком много платежей")
		}
		for _, entry := range docs(d["schedule"]) {
			if e := fields(entry, "date amount status"); e != nil {
				return e
			}
			if _, e := day(text(entry, "date")); e != nil {
				return e
			}
			if n, ok := entry["amount"].(float64); !ok || math.IsNaN(n) || math.IsInf(n, 0) || n < 0 || n > 1e13 || math.Abs(n*100-math.Round(n*100)) > .001 {
				return bad("Некорректная сумма графика")
			}
			if _, ok := entry["status"]; !ok {
				entry["status"] = "expected"
			}
			if !in(text(entry, "status"), "expected received missed cancelled") {
				return bad("Некорректный статус графика")
			}
			sum += number(entry, "amount")
		}
		if math.Abs(sum-number(d, "total")) > 0.011 {
			return bad("Сумма графика должна совпадать с суммой договора")
		}
	case "operation":
		d["category_method"] = "user"
		d["is_internal"] = domain.Category(text(d, "category")).IsInternal()
	}
	if kind == "event" || kind == "recurring" {
		if !in(text(d, "direction"), "in out") {
			return bad("Направление: in или out")
		}
	}
	return nil
}
func in(v, options string) bool { return strings.Contains(" "+options+" ", " "+v+" ") && v != "" }
