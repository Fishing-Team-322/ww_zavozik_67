package httpapi_test

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/config"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestSandboxMarketplaceWiringSecretsAndBankIsolation(t *testing.T) {
	h := integration(t)
	owner, _ := h.register("marketplaces@example.invalid")
	other, _ := h.register("not-marketplace-owner@example.invalid")
	service, e := product.New(h.db, config.Config{IntegrationSandbox: true, PublicURL: "http://localhost:8080", FrontendURL: "http://localhost:3000", DataEncryptionKey: base64.StdEncoding.EncodeToString(bytes.Repeat([]byte("k"), 32))}, nil)
	if e != nil {
		t.Fatal(e)
	}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: service, Log: testLogger()}).Handler()
	r := h.call("POST", "/v1/companies", `{"name":"Marketplace test","legal_form":"ООО","industry":"tests"}`, owner)
	status(t, r, 201)
	cid := decode[platform.Company](t, r).ID
	base := "/v1/companies/" + cid
	call := func(method, path string, body any, want int) product.Doc {
		t.Helper()
		raw := ""
		if body != nil {
			b, _ := json.Marshal(body)
			raw = string(b)
		}
		r := h.call(method, path, raw, owner)
		status(t, r, want)
		if r.Body.Len() == 0 {
			return nil
		}
		return decode[product.Doc](t, r)
	}
	for _, kind := range []string{"wb", "ozon"} {
		source := call("POST", base+"/sources", product.Doc{"kind": kind, "title": kind, "config": product.Doc{"api_key": "sandbox-key", "client_id": "sandbox-client", "from": "2026-10-01", "to": "2026-10-07"}}, 201)
		if strings.Contains(string(mustJSON(t, source)), "sandbox-key") {
			t.Fatal("secret leaked in source")
		}
		sid := source["id"].(string)
		rotated := call("PATCH", "/v1/sources/"+sid, product.Doc{"config": product.Doc{"api_key": "sandbox-key"}}, 200)
		if rotated["status"] != "pending" || strings.Contains(string(mustJSON(t, rotated)), "sandbox-key") {
			t.Fatal("credential rotation status or masking failed")
		}
		call("POST", "/v1/sources/"+sid+"/test", nil, 200)
		for run := 0; run < 2; run++ {
			job := call("POST", "/v1/sources/"+sid+"/sync", nil, 202)
			for i := 0; i < 30; i++ {
				worked, e := service.ProcessOne(context.Background())
				if e != nil {
					t.Fatal(e)
				}
				if !worked {
					break
				}
			}
			done := call("GET", "/v1/jobs/"+job["id"].(string), nil, 200)
			if done["status"] != "done" {
				t.Fatal("sync failed", done)
			}
			result := done["result"].(map[string]any)
			if result["bank_operations_added"] != float64(0) {
				t.Fatal("marketplace became bank facts")
			}
			if run == 1 && result["reports_added"] != float64(0) {
				t.Fatal("repeat created duplicate", result)
			}
		}
		var sealed []byte
		if e := h.db.Pool.QueryRow(context.Background(), "SELECT config_secret FROM sources WHERE id=$1", sid).Scan(&sealed); e != nil {
			t.Fatal(e)
		}
		if len(sealed) == 0 || bytes.Contains(sealed, []byte("sandbox-key")) {
			t.Fatal("credentials not encrypted")
		}
	}
	reports := h.call("GET", base+"/marketplace-reports", "", owner)
	status(t, reports, 200)
	rows := decode[[]product.Doc](t, reports)
	if len(rows) != 4 {
		t.Fatalf("report rows %d", len(rows))
	}
	for _, row := range rows {
		if row["data_mode"] != "mock" || row["bank_fact"] != false || row["forecast_eligible"] != false {
			t.Fatal("incorrect accounting trust", row)
		}
	}
	status(t, h.call("GET", base+"/marketplace-reports", "", other), 404)
	var n int
	if e := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM operations WHERE company_id=$1", cid).Scan(&n); e != nil || n != 0 {
		t.Fatal("bank facts corrupted", n, e)
	}
	sheet := call("POST", base+"/sources", product.Doc{"kind": "gsheets", "title": "Synthetic sheet", "config": product.Doc{"api_key": "sandbox-key", "spreadsheet_id": "synthetic-sheet"}}, 201)
	sheetPath := "/v1/sources/" + sheet["id"].(string)
	status(t, h.call("POST", sheetPath+"/sheet-preview", "", other), 404)
	preview := call("POST", sheetPath+"/sheet-preview", nil, 200)
	if len(preview["rows"].([]any)) != 1 {
		t.Fatal("sheet preview missing")
	}
	call("POST", sheetPath+"/sheet-mapping", product.Doc{}, 400)
	call("POST", sheetPath+"/sheet-mapping", product.Doc{"mapping": product.Doc{"date": "missing", "amount": "amount", "direction": "direction"}}, 400)
	for run := 0; run < 2; run++ {
		job := call("POST", sheetPath+"/sheet-mapping", product.Doc{"mapping": preview["proposed_mapping"]}, 202)
		for i := 0; i < 30; i++ {
			worked, err := service.ProcessOne(context.Background())
			if err != nil {
				t.Fatal(err)
			}
			if !worked {
				break
			}
		}
		done := call("GET", "/v1/jobs/"+job["id"].(string), nil, 200)
		if done["status"] != "done" {
			t.Fatal("sheet import failed", done)
		}
	}
	if e := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM operations WHERE company_id=$1", cid).Scan(&n); e != nil || n != 1 {
		t.Fatal("sheet duplicated", n, e)
	}
	call("PATCH", sheetPath, product.Doc{"enabled": false}, 200)
	call("POST", sheetPath+"/sheet-preview", nil, 409)
	enabled := call("PATCH", sheetPath, product.Doc{"enabled": true}, 200)
	if enabled["status"] != "pending" {
		t.Fatal("re-enabled source retained disconnected status", enabled)
	}
}
func mustJSON(t *testing.T, value any) []byte {
	t.Helper()
	b, e := json.Marshal(value)
	if e != nil {
		t.Fatal(e)
	}
	return b
}
