package httpapi_test

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/xuri/excelize/v2"
)

func TestProductEndToEnd(t *testing.T) {
	h := integration(t)
	ctx := context.Background()
	owner, _ := h.register("finance@example.com")
	other, _ := h.register("foreign@example.com")
	admin, _ := h.register("admin@example.com")
	if _, e := h.db.Pool.Exec(ctx, "UPDATE users SET role='admin' WHERE email='admin@example.com'"); e != nil {
		t.Fatal(e)
	}
	service := &product.Service{DB: h.db, Fallback: forecast.SeasonalNaive{}, EncryptionKey: bytes.Repeat([]byte("x"), 32), ReportsDir: "../../../ml/reports/metrics"}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: service, Fallback: forecast.SeasonalNaive{}, Log: testLogger()}).Handler()
	call := func(method, path string, body any, token string, want int) *httptest.ResponseRecorder {
		t.Helper()
		data := ""
		if body != nil {
			raw, e := json.Marshal(body)
			if e != nil {
				t.Fatal(e)
			}
			data = string(raw)
		}
		r := h.call(method, path, data, token)
		status(t, r, want)
		return r
	}
	create := func(path string, b product.Doc) product.Doc {
		t.Helper()
		return decode[product.Doc](t, call("POST", path, b, owner, 201))
	}
	company := decode[product.Doc](t, call("POST", "/v1/companies", product.Doc{"name": "Финансы", "legal_form": "ООО", "industry": "services", "inn": "7707083893"}, owner, 201))
	cid := company["id"].(string)
	base := "/v1/companies/" + cid
	next := domain.Day(time.Now().UTC()).AddDate(0, 0, 1).Format(domain.DateLayout)
	call("GET", base+"/dashboard", nil, owner, 200)
	call("GET", base+"/forecast", nil, owner, 422)
	csv := "date,amount,direction,counterparty_name,counterparty_inn,purpose,balance_eod\n"
	balance := 10000.0
	for i := 55; i >= 0; i-- {
		dt := domain.Day(time.Now().UTC()).AddDate(0, 0, -i).Format(domain.DateLayout)
		balance += 40
		csv += fmt.Sprintf("%s,100,in,Клиент,7700000001,Оплата услуг,%.2f\n%s,60,out,Поставщик,7700000002,Оплата поставщику,%.2f\n", dt, balance, dt, balance)
	}
	upload := func(filename string, data []byte) product.Doc {
		t.Helper()
		buf := &bytes.Buffer{}
		m := multipart.NewWriter(buf)
		part, e := m.CreateFormFile("file", filename)
		if e != nil {
			t.Fatal(e)
		}
		part.Write(data)
		m.Close()
		req := httptest.NewRequest("POST", base+"/uploads", buf)
		req.Header.Set("Authorization", "Bearer "+owner)
		req.Header.Set("Content-Type", m.FormDataContentType())
		out := httptest.NewRecorder()
		h.handler.ServeHTTP(out, req)
		status(t, out, 202)
		return decode[product.Doc](t, out)
	}
	drain := func() {
		t.Helper()
		for i := 0; i < 200; i++ {
			worked, e := service.ProcessOne(ctx)
			if e != nil {
				t.Fatal(e)
			}
			if !worked {
				return
			}
		}
		t.Fatal("worker did not settle")
	}
	job := upload("statement.csv", []byte(csv))
	drain()
	result := decode[product.Doc](t, call("GET", "/v1/jobs/"+job["id"].(string), nil, owner, 200))
	if result["status"] != "done" {
		t.Fatalf("import failed: %+v", result)
	}
	importRef := result["result_ref"].(string)
	imp := decode[product.Doc](t, call("GET", importRef, nil, owner, 200))
	if imp["added"] != float64(112) {
		t.Fatal("added", imp)
	}
	repeated := upload("statement-again.csv", []byte(csv))
	drain()
	repeatResult := decode[product.Doc](t, call("GET", "/v1/jobs/"+repeated["id"].(string), nil, owner, 200))
	repeatReport := decode[product.Doc](t, call("GET", repeatResult["result_ref"].(string), nil, owner, 200))
	if repeatReport["added"] != float64(0) || repeatReport["duplicates"] != float64(112) {
		t.Fatal("duplicate import", repeatReport)
	}
	operations := decode[product.Doc](t, call("GET", base+"/operations?limit=3", nil, owner, 200))
	items := operations["items"].([]any)
	if len(items) != 3 || operations["next_cursor"] == nil {
		t.Fatal("pagination", operations)
	}
	opID := items[0].(map[string]any)["id"].(string)
	call("PATCH", "/v1/operations/"+opID, product.Doc{"category": "services"}, owner, 200)
	call("PATCH", "/v1/operations/"+opID, product.Doc{"category": "services"}, other, 404)
	summary := decode[product.Doc](t, call("GET", base+"/operations/summary", nil, owner, 200))
	if summary["total_in"] != float64(5600) || summary["total_out"] != float64(3360) {
		t.Fatal("summary", summary)
	}
	exported := call("GET", base+"/operations/export?format=xlsx", nil, owner, 200)
	workbook, e := excelize.OpenReader(bytes.NewReader(exported.Body.Bytes()))
	if e != nil {
		t.Fatal(e)
	}
	workbook.Close()
	invoice := create(base+"/invoices", product.Doc{"number": "INV-1", "direction": "issued", "amount": 300, "issued_at": next, "due_at": next, "counterparty_name": "Клиент"})
	contract := create(base+"/contracts", product.Doc{"number": "C-1", "direction": "out", "total": 200, "schedule": []product.Doc{{"date": next, "amount": 200, "status": "expected"}}, "counterparty_name": "Поставщик"})
	events := decode[[]product.Doc](t, call("GET", base+"/events", nil, owner, 200))
	if len(events) != 2 {
		t.Fatal("document projections", events)
	}
	event := create(base+"/events", product.Doc{"date": next, "amount": 50000, "direction": "out", "title": "Станок"})
	pattern := create(base+"/recurring", product.Doc{"title": "Аренда", "direction": "out", "amount": 100, "period": "monthly", "day_of_month": 28, "category": "rent"})
	call("PATCH", "/v1/recurring/"+pattern["id"].(string), product.Doc{"amount": 120, "confirmed": true}, owner, 200)
	scenario := create(base+"/scenarios", product.Doc{"title": "Выручка ниже", "steps": []product.Doc{{"kind": "scale_revenue", "factor": 0.8}}})
	call("PATCH", "/v1/scenarios/"+scenario["id"].(string), product.Doc{"title": "Проверка изменения сценария"}, owner, 200)
	forecastResponse := decode[product.Doc](t, call("GET", base+"/forecast", nil, owner, 200))
	if !forecastResponse["fallback_used"].(bool) || forecastResponse["flow_scope"] != forecast.BusinessFlowScope {
		t.Fatal("ML metadata", forecastResponse)
	}
	if len(forecastResponse["gaps"].([]any)) == 0 {
		t.Fatal("expected gap")
	}
	gapID := forecastResponse["gaps"].([]any)[0].(map[string]any)["id"].(string)
	gap := decode[product.Doc](t, call("GET", base+"/gaps/"+gapID, nil, owner, 200))
	actions := gap["actions"].([]any)
	if len(actions) == 0 {
		t.Fatal("actions")
	}
	actionID := actions[0].(map[string]any)["id"].(string)
	call("POST", base+"/gaps/"+gapID+"/simulate", product.Doc{"action_ids": []string{actionID}}, owner, 200)
	call("POST", "/v1/actions/"+actionID+"/apply", nil, owner, 200)
	call("POST", "/v1/actions/"+actionID+"/apply", nil, owner, 200)
	call("POST", base+"/forecast/preview", product.Doc{"changes": []product.Doc{{"id": event["id"], "date": domain.Day(time.Now().UTC()).AddDate(0, 0, 60).Format(domain.DateLayout)}}}, owner, 200)
	call("POST", base+"/scenarios/preview", product.Doc{"steps": []product.Doc{{"kind": "add_expense", "amount": 700, "date": next}}}, owner, 200)
	for _, route := range []string{base + "/dashboard", base + "/forecast/days/" + next, base + "/calendar?month=" + next[:7], base + "/forecast/accuracy", base + "/plan-fact", base + "/plan-fact/missed", base + "/taxes", base + "/retro", base + "/counterparties", base + "/counterparties/concentration", base + "/imports", base + "/sources", base + "/alerts", base + "/recurring", base + "/invoices", base + "/contracts", base + "/scenarios", "/v1/scenarios/" + scenario["id"].(string) + "/compare", base + "/scenarios/" + scenario["id"].(string) + "/compare", "/v1/categories", "/v1/scenario-presets", "/v1/models/quality"} {
		call("GET", route, nil, owner, 200)
	}
	counterparties := decode[[]product.Doc](t, call("GET", base+"/counterparties", nil, owner, 200))
	cpID := counterparties[0]["id"].(string)
	call("GET", base+"/counterparties/"+cpID, nil, owner, 200)
	call("POST", base+"/operations/recategorize", product.Doc{"counterparty_id": cpID, "category": "services", "apply_to": "future"}, owner, 200)
	call("POST", base+"/events/parse", product.Doc{"text": "клиент Альфа обещал 300 тысяч 20-го"}, owner, 200)
	call("POST", base+"/alerts/read-all", nil, owner, 204)
	exportedJob := decode[product.Doc](t, call("POST", base+"/export", nil, owner, 202))
	drain()
	exportStatus := decode[product.Doc](t, call("GET", "/v1/jobs/"+exportedJob["id"].(string), nil, owner, 200))
	if exportStatus["status"] != "done" {
		t.Fatal("export failed", exportStatus)
	}
	archive := call("GET", exportStatus["result_ref"].(string), nil, owner, 200)
	z, e := zip.NewReader(bytes.NewReader(archive.Body.Bytes()), int64(archive.Body.Len()))
	if e != nil || len(z.File) < 8 {
		t.Fatal("invalid export", e)
	}
	call("GET", "/v1/jobs/"+exportedJob["id"].(string), nil, other, 404)
	call("GET", exportStatus["result_ref"].(string), nil, other, 404)
	source := create(base+"/sources", product.Doc{"kind": "manual", "title": "Ручной источник", "config": product.Doc{"password": "secret-never-return"}})
	rawSource := call("GET", "/v1/sources/"+source["id"].(string), nil, owner, 200)
	if strings.Contains(rawSource.Body.String(), "secret-never-return") {
		t.Fatal("source secret leak")
	}
	call("POST", "/v1/sources/"+source["id"].(string)+"/test", nil, owner, 200)
	call("POST", "/v1/sources/"+source["id"].(string)+"/sync", nil, owner, 409)
	call("PATCH", "/v1/sources/"+source["id"].(string), product.Doc{"enabled": false}, owner, 200)
	call("DELETE", "/v1/sources/"+source["id"].(string), product.Doc{"keep_data": true}, owner, 204)
	for _, route := range []string{base + "/forecast", base + "/operations", base + "/events", base + "/scenarios", base + "/sources", base + "/calendar?month=" + next[:7], base + "/dashboard", base + "/counterparties"} {
		call("GET", route, nil, other, 404)
	}
	call("GET", "/v1/fns/lookup?inn=7707083893", nil, owner, 503)
	for _, route := range []string{"overview", "users", "companies", "companies/" + cid, "integrations", "integrations/stats", "models", "models/drift", "classifier", "antifraud/signals", "antifraud/stats", "audit"} {
		call("GET", "/v1/admin/"+route, nil, owner, 403)
		call("GET", "/v1/admin/"+route, nil, admin, 200)
	}
	call("POST", "/v1/admin/models/auto/retrain", nil, admin, 503)
	call("PATCH", "/v1/invoices/"+invoice["id"].(string), product.Doc{"status": "paid"}, owner, 200)
	call("PATCH", "/v1/contracts/"+contract["id"].(string), product.Doc{"prepayment": 50}, owner, 200)
	for _, resource := range []struct {
		kind string
		d    product.Doc
	}{{"events", event}, {"recurring", pattern}, {"scenarios", scenario}, {"invoices", invoice}, {"contracts", contract}} {
		call("DELETE", "/v1/"+resource.kind+"/"+resource.d["id"].(string), nil, owner, 204)
	}
	// Blocking invalidates already issued tokens and prevents password login.
	var otherID string
	if e = h.db.Pool.QueryRow(ctx, "SELECT id::text FROM users WHERE email='foreign@example.com'").Scan(&otherID); e != nil {
		t.Fatal(e)
	}
	call("PATCH", "/v1/admin/users/"+otherID, product.Doc{"status": "blocked", "reason": "integration test"}, admin, 200)
	call("GET", "/v1/me", nil, other, 401)
}

func TestProductInputNeverPanics(t *testing.T) {
	h := integration(t)
	owner, _ := h.register("inputs@example.com")
	company := decode[product.Doc](t, h.call("POST", "/v1/companies", `{"name":"Inputs","legal_form":"ИП","industry":"services"}`, owner))
	base := "/v1/companies/" + company["id"].(string)
	for _, endpoint := range []string{"events", "recurring", "scenarios", "invoices", "contracts", "sources"} {
		for _, bad := range []string{`{}`, `{"amount":"wrong"}`, `{"company_id":"forged"}`, `{"title":null}`} {
			r := h.call("POST", base+"/"+endpoint, bad, owner)
			if r.Code >= 500 {
				t.Fatalf("%s %s: %d %s", endpoint, bad, r.Code, r.Body)
			}
		}
	}
}

func testLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }
