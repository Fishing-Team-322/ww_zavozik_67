package httpapi_test

import (
	"context"
	"encoding/json"
	"math"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/google/uuid"
)

func seedCaseHistory(t *testing.T, h *harness, cid string, asOf time.Time, days int) {
	t.Helper()
	balance := 100000.0
	for i := days - 1; i >= 0; i-- {
		dt := asOf.AddDate(0, 0, -i)
		balance += 100
		for _, r := range []struct {
			direction       string
			amount          float64
			category, party string
		}{{"in", 500, "revenue_b2b", "Клиент"}, {"out", 400, "supplier", "Поставщик"}} {
			id := uuid.NewString()
			_, e := h.db.Pool.Exec(context.Background(), `INSERT INTO operations(id,company_id,op_date,amount,direction,counterparty_name,purpose,balance_eod,category,category_method,dedup_hash,extra) VALUES($1,$2,$3,$4,$5,$6,'Synthetic fixture',$7,$8,'rule',$1,'{}')`, id, cid, dt, r.amount, r.direction, r.party, balance, r.category)
			if e != nil {
				t.Fatal(e)
			}
		}
	}
}
func drainCase(t *testing.T, s *product.Service) {
	t.Helper()
	for i := 0; i < 200; i++ {
		worked, e := s.ProcessOne(context.Background())
		if e != nil {
			t.Fatal(e)
		}
		if !worked {
			return
		}
	}
	t.Fatal("worker did not settle")
}

func TestTaxLiabilityChangesForecastExactlyOnce(t *testing.T) {
	h := integration(t)
	owner, _ := h.register("tax-owner@example.test")
	other, _ := h.register("tax-other@example.test")
	s := &product.Service{DB: h.db, Fallback: forecast.SeasonalNaive{}}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: s, Log: testLogger()}).Handler()
	r := h.call("POST", "/v1/companies", `{"name":"Tax case","legal_form":"ООО","industry":"services"}`, owner)
	status(t, r, 201)
	cid := decode[product.Doc](t, r)["id"].(string)
	base := "/v1/companies/" + cid
	seedCaseHistory(t, h, cid, time.Date(2026, 10, 23, 0, 0, 0, 0, time.UTC), 90)
	getForecast := func() product.Doc {
		r := h.call("GET", base+"/forecast", "", owner)
		status(t, r, 200)
		return decode[product.Doc](t, r)
	}
	before := getForecast()
	b := product.Doc{"request_id": uuid.NewString(), "kind": "usn_advance", "period": "9m", "year": 2026, "amount": 5000, "title": "Налог из подтверждённого расчёта", "source_ref": "Расчёт бухгалтера", "confirmed": false, "additional": true}
	call := func(op, path string, b any, token string, want int) product.Doc {
		raw := ""
		if b != nil {
			v, _ := json.Marshal(b)
			raw = string(v)
		}
		r := h.call(op, path, raw, token)
		status(t, r, want)
		if want == 204 {
			return nil
		}
		return decode[product.Doc](t, r)
	}
	preview := call("POST", base+"/taxes/preview", b, owner, 200)
	if len(preview["payments"].([]any)) != 1 {
		t.Fatal(preview)
	}
	call("POST", base+"/taxes", b, owner, 400)
	b["confirmed"] = true
	created := call("POST", base+"/taxes", b, owner, 201)
	id := created["id"].(string)
	repeated := call("POST", base+"/taxes", b, owner, 201)
	if repeated["id"] != id {
		t.Fatal("idempotency failed")
	}
	firstRequest := b["request_id"]
	b["request_id"] = uuid.NewString()
	call("POST", base+"/taxes", b, owner, 409)
	b["request_id"] = firstRequest
	b["amount"] = 5001
	call("POST", base+"/taxes", b, owner, 409)
	b["amount"] = 5000
	call("GET", base+"/taxes", nil, other, 404)
	call("POST", "/v1/taxes/"+id+"/cancel", nil, other, 404)
	updates := call("GET", base+"/updates", nil, owner, 200)
	if updates["pending_jobs"].(float64) < 1 {
		t.Fatal("recompute not queued", updates)
	}
	after := getForecast()
	a, bp := before["points"].([]any), after["points"].([]any)
	for i, old := range a {
		p := old.(map[string]any)
		n := bp[i].(map[string]any)
		want := 0.0
		if p["date"].(string) >= "2026-10-28" {
			want = 5000
		}
		if math.Abs(p["p50"].(float64)-n["p50"].(float64)-want) > .01 {
			t.Fatal("tax counted twice or on wrong day", p, n)
		}
	}
	drainCase(t, s)
	list := call("GET", base+"/taxes?year=2026", nil, owner, 200)
	if len(list["obligations"].([]any)) != 1 {
		t.Fatal(list)
	}
	call("POST", "/v1/taxes/"+id+"/cancel", nil, owner, 204)
	call("POST", "/v1/taxes/"+id+"/cancel", nil, owner, 204)
	final := getForecast()
	for i, p := range final["points"].([]any) {
		if math.Abs(p.(map[string]any)["p50"].(float64)-a[i].(map[string]any)["p50"].(float64)) > .01 {
			t.Fatal("cancelled tax affects forecast")
		}
	}
	// A separate, ordinary liability appears in the calendar but is not added to ML again.
	b["request_id"], b["additional"] = uuid.NewString(), false
	ordinary := call("POST", base+"/taxes", b, owner, 201)
	final = getForecast()
	for i, p := range final["points"].([]any) {
		if math.Abs(p.(map[string]any)["p50"].(float64)-a[i].(map[string]any)["p50"].(float64)) > .01 {
			t.Fatal("ordinary tax duplicated model flow")
		}
	}
	// Matching uses the tax category, not one bank's spelling of the treasury payee.
	actualID := uuid.NewString()
	_, e := h.db.Pool.Exec(context.Background(), `INSERT INTO operations(id,company_id,op_date,amount,direction,counterparty_name,purpose,balance_eod,category,category_method,dedup_hash,extra) VALUES($1,$2,'2026-10-28',5000,'out','Казначейство России','Подтверждённый налог',100000,'tax','rule',$1,'{}')`, actualID, cid)
	if e != nil {
		t.Fatal(e)
	}
	if e = s.DB.QueueRecompute(context.Background(), ownerID(t, h, owner), cid); e != nil {
		t.Fatal(e)
	}
	drainCase(t, s)
	call("POST", "/v1/taxes/"+ordinary["id"].(string)+"/cancel", nil, owner, 204)
	list = call("GET", base+"/taxes", nil, owner, 200)
	for _, v := range list["obligations"].([]any) {
		d := v.(map[string]any)
		if d["id"] == ordinary["id"] {
			if d["paid_amount"] != float64(5000) || d["payments"].([]any)[0].(map[string]any)["status"] != "received" {
				t.Fatal("paid history was lost", d)
			}
		}
	}
}

func TestWorkerPlanFactLatePaymentAndAlerts(t *testing.T) {
	h := integration(t)
	owner, _ := h.register("plan-owner@example.test")
	s := &product.Service{DB: h.db, Fallback: forecast.SeasonalNaive{}}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: s, Log: testLogger()}).Handler()
	r := h.call("POST", "/v1/companies", `{"name":"Plan case","legal_form":"ООО","industry":"services"}`, owner)
	status(t, r, 201)
	cid := decode[product.Doc](t, r)["id"].(string)
	base := "/v1/companies/" + cid
	asOf := time.Date(2026, 10, 23, 0, 0, 0, 0, time.UTC)
	seedCaseHistory(t, h, cid, asOf, 60)
	r = h.call("POST", base+"/events", `{"title":"Оплата клиента","date":"2026-10-20","amount":7777,"direction":"in","counterparty_name":"Особый клиент"}`, owner)
	status(t, r, 201)
	event := decode[product.Doc](t, r)
	drainCase(t, s)
	r = h.call("GET", base+"/plan-fact/missed", "", owner)
	status(t, r, 200)
	missed := decode[product.Doc](t, r)
	if len(missed["missed"].([]any)) != 1 {
		t.Fatal(missed)
	}
	r = h.call("GET", base+"/alerts?kind=missed_payment", "", owner)
	status(t, r, 200)
	if len(decode[product.Doc](t, r)["items"].([]any)) != 1 {
		t.Fatal("missing late alert", r.Body)
	}
	r = h.call("GET", base+"/plan-fact?from=2026-10-20&to=2026-10-24", "", owner)
	status(t, r, 200)
	rows := decode[[]product.Doc](t, r)
	if len(rows) != 5 || rows[4]["fact_in"] != nil || rows[4]["deviation"] != nil || rows[4]["observed"] != false {
		t.Fatal("missing fact invented as zero", rows)
	}
	// The actual payment arrives two weeks late, with explicit balance coverage.
	id := uuid.NewString()
	dt := asOf.AddDate(0, 0, 11)
	_, e := h.db.Pool.Exec(context.Background(), `INSERT INTO operations(id,company_id,op_date,amount,direction,counterparty_name,purpose,balance_eod,category,category_method,dedup_hash,extra) VALUES($1,$2,$3,7777,'in','Особый клиент','Late fixture',120000,'revenue_b2b','rule',$1,'{}')`, id, cid, dt)
	if e != nil {
		t.Fatal(e)
	}
	if e = s.DB.QueueRecompute(context.Background(), ownerID(t, h, owner), cid); e != nil {
		t.Fatal(e)
	}
	drainCase(t, s)
	r = h.call("GET", base+"/events", "", owner)
	status(t, r, 200)
	events := decode[[]product.Doc](t, r)
	for _, d := range events {
		if d["id"] == event["id"] && d["status"] != "received" {
			t.Fatal("late payment did not reconcile", d)
		}
	}
	if e = s.DB.QueueRecompute(context.Background(), ownerID(t, h, owner), cid); e != nil {
		t.Fatal(e)
	}
	drainCase(t, s)
	r = h.call("GET", base+"/alerts?kind=missed_payment", "", owner)
	status(t, r, 200)
	if len(decode[product.Doc](t, r)["items"].([]any)) != 1 {
		t.Fatal("duplicate late alert")
	}
	r = h.call("GET", base+"/updates", "", owner)
	status(t, r, 200)
	u := decode[product.Doc](t, r)
	if u["pending_jobs"] != float64(0) || u["forecast_revision"] != u["data_revision"] {
		t.Fatal("worker forecast not current", u)
	}
	r = h.call("GET", base+"/plan-fact/missed", "", owner)
	status(t, r, 200)
	change := decode[product.Doc](t, r)["forecast_change"].(map[string]any)
	if change["revision_before"] == nil {
		t.Fatal("no saved revision comparison", change)
	}
}
func ownerID(t *testing.T, h *harness, token string) string {
	t.Helper()
	r := h.call("GET", "/v1/me", "", token)
	status(t, r, 200)
	return decode[product.Doc](t, r)["id"].(string)
}
