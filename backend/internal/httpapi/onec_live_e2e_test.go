package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/google/uuid"
)

// Run with TEST_DATABASE_URL and LIVE_ONEC_CONFIG pointing to a local read-only
// demo configuration. No infobase data or credentials are checked into Git.
func TestLiveOneCBackendFacts(t *testing.T) {
	path := os.Getenv("LIVE_ONEC_CONFIG")
	if path == "" {
		t.Skip("set LIVE_ONEC_CONFIG for the local educational OData infobase")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cfg product.Doc
	if err = json.Unmarshal(raw, &cfg); err != nil {
		t.Fatal(err)
	}
	hasPlans := cfg["plan_config"] != nil
	address, err := url.Parse(cfg["base_url"].(string))
	if err != nil {
		t.Fatal(err)
	}
	if username := os.Getenv("LIVE_ONEC_USERNAME"); username != "" {
		cfg["username"] = username
		cfg["password"] = os.Getenv("LIVE_ONEC_PASSWORD")
	}
	h := integration(t)
	owner, _ := h.register("live-onec-owner@example.test")
	outsider, _ := h.register("live-onec-outsider@example.test")
	svc := &product.Service{DB: h.db, Fallback: forecast.SeasonalNaive{}, EncryptionKey: bytes.Repeat([]byte("k"), 32), AllowedSourceHosts: []string{address.Host}}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: svc, Log: testLogger()}).Handler()
	call := func(method, path string, body any, token string, want int) product.Doc {
		t.Helper()
		var data string
		if body != nil {
			encoded, e := json.Marshal(body)
			if e != nil {
				t.Fatal(e)
			}
			data = string(encoded)
		}
		response := h.call(method, path, data, token)
		status(t, response, want)
		return decode[product.Doc](t, response)
	}
	company := call(http.MethodPost, "/v1/companies", product.Doc{"name": "Live 1C QA", "legal_form": "ООО", "industry": "services", "inn": cfg["company_inn"]}, owner, 201)
	cid := company["id"].(string)
	source := call(http.MethodPost, "/v1/companies/"+cid+"/sources", product.Doc{"title": "Local educational 1C", "kind": "onec_odata", "config": cfg}, owner, 201)
	sid := source["id"].(string)
	checked := call(http.MethodPost, "/v1/sources/"+sid+"/test", nil, owner, 200)
	if checked["ok"] != true || checked["ready_to_sync"] != true {
		t.Fatal("live OData mapping did not pass metadata test")
	}
	factCount, planCount := 0, 0
	for round := 0; round < 2; round++ {
		job := call(http.MethodPost, "/v1/sources/"+sid+"/sync", nil, owner, 202)
		jid := job["id"].(string)
		var done product.Doc
		for attempt := 0; attempt < 20; attempt++ {
			worked, e := svc.ProcessOne(context.Background())
			if e != nil {
				t.Fatal(e)
			}
			done = call(http.MethodGet, "/v1/jobs/"+jid, nil, owner, 200)
			if done["status"] == "done" || done["status"] == "failed" {
				break
			}
			if !worked {
				t.Fatal("sync job did not complete")
			}
		}
		if done["status"] != "done" {
			t.Fatal("live sync failed; inspect job status")
		}
		result := done["result"].(map[string]any)
		if round == 0 {
			factCount = int(result["added"].(float64))
			if factCount < 14 {
				t.Fatalf("expected at least 14 live bank facts, got %d", factCount)
			}
		} else if result["added"] != float64(0) || result["duplicates"] != float64(factCount) {
			t.Fatalf("unexpected live sync counters round %d: added=%v duplicates=%v", round, result["added"], result["duplicates"])
		}
		if hasPlans {
			if round == 0 {
				planCount = int(result["plans_added"].(float64))
				if planCount < 6 {
					t.Fatalf("expected at least 6 live invoices, got %d", planCount)
				}
			} else if result["plans_added"] != float64(0) || result["plans_duplicates"] != float64(planCount) {
				t.Fatalf("unexpected live plan counters round %d: added=%v duplicates=%v", round, result["plans_added"], result["plans_duplicates"])
			}
		}
	}
	operations := call(http.MethodGet, "/v1/companies/"+cid+"/operations?limit=100", nil, owner, 200)
	items := operations["items"].([]any)
	if len(items) != factCount {
		t.Fatalf("want %d unique live operations, got %d", factCount, len(items))
	}
	status(t, h.call(http.MethodGet, "/v1/companies/"+cid+"/operations", "", outsider), 404)
	if hasPlans {
		response := h.call(http.MethodGet, "/v1/companies/"+cid+"/events", "", owner)
		status(t, response, 200)
		events := decode[[]product.Doc](t, response)
		if len(events) != planCount {
			t.Fatalf("want %d live invoices, got %d", planCount, len(events))
		}
		var baselineOpen, partial, cancelled, eligible int
		var partialEvent product.Doc
		for _, event := range events {
			if event["total_kopecks"] == float64(35_000_000) {
				if event["payment_status"] == "cancelled" {
					cancelled++
					if event["remaining_kopecks"] != float64(0) || event["forecast_eligible"] != false {
						t.Fatalf("cancelled invoice still open: %v", event)
					}
				} else {
					partial++
					partialEvent = event
					if event["paid_kopecks"] != float64(10_000_000) || event["remaining_kopecks"] != float64(25_000_000) || event["status"] != "undated" || event["payment_status"] != "partially_paid" {
						t.Fatalf("live partial payment is not 350000 = 100000 + 250000: %v", event)
					}
				}
			}
			if event["remaining_kopecks"].(float64) > 0 {
				if event["remaining_kopecks"] == float64(2_500_000) {
					baselineOpen++
				}
				if event["status"] != "undated" {
					t.Fatalf("unexpected open live obligation: %v", event)
				}
			}
			if event["forecast_eligible"] == true {
				eligible++
			}
		}
		if baselineOpen != 1 || eligible != 0 || planCount >= 7 && partial+cancelled != 1 {
			t.Fatalf("live obligations: baseline_open=%d partial=%d cancelled=%d eligible=%d", baselineOpen, partial, cancelled, eligible)
		}
		status(t, h.call(http.MethodGet, "/v1/companies/"+cid+"/events", "", outsider), 404)
		if os.Getenv("LIVE_ONEC_CANCEL") == "1" {
			if address.Hostname() != "127.0.0.1" || address.Path != "/codexobligations/odata/standard.odata/" || partial != 1 {
				t.Fatal("live cancellation is restricted to the isolated 1C clone with one partial test invoice")
			}
			prefix, ref, ok := strings.Cut(partialEvent["external_id"].(string), ":")
			if !ok || prefix != "Document_СчетНаОплатуПокупателю" {
				t.Fatal("unexpected test invoice identity")
			}
			if _, err := uuid.Parse(ref); err != nil {
				t.Fatal(err)
			}
			cancelOneCInvoice(t, address.String(), ref, cfg)
			job := call(http.MethodPost, "/v1/sources/"+sid+"/sync", nil, owner, 202)
			var result map[string]any
			for attempt := 0; attempt < 20; attempt++ {
				if _, e := svc.ProcessOne(context.Background()); e != nil {
					t.Fatal(e)
				}
				done := call(http.MethodGet, "/v1/jobs/"+job["id"].(string), nil, owner, 200)
				if done["status"] == "done" {
					result = done["result"].(map[string]any)
					break
				}
				if done["status"] == "failed" {
					t.Fatal("live cancellation sync failed")
				}
			}
			if result == nil || result["plans_updated"] != float64(1) || result["plans_duplicates"] != float64(planCount-1) || result["added"] != float64(0) {
				t.Fatalf("live cancellation changed unexpected rows: %v", result)
			}
			response = h.call(http.MethodGet, "/v1/companies/"+cid+"/events", "", owner)
			status(t, response, 200)
			events = decode[[]product.Doc](t, response)
			var found bool
			for _, event := range events {
				if event["id"] != partialEvent["id"] {
					continue
				}
				found = true
				if event["payment_status"] != "cancelled" || event["remaining_kopecks"] != float64(0) || event["paid_kopecks"] != float64(10_000_000) || event["version"] != float64(2) || event["forecast_eligible"] != false {
					t.Fatalf("cancelled live plan did not update in place: %v", event)
				}
			}
			if !found || len(events) != planCount {
				t.Fatal("live cancellation changed plan identity or count")
			}
			var versions int
			if err := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM onec_plan_versions WHERE company_id=$1 AND source_id=$2 AND external_id=$3 AND direction='in'", cid, sid, partialEvent["external_id"]).Scan(&versions); err != nil || versions != 2 {
				t.Fatalf("live history: versions=%d err=%v", versions, err)
			}
		}
	}
}

func cancelOneCInvoice(t *testing.T, root, ref string, cfg product.Doc) {
	t.Helper()
	client := &http.Client{Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	entity := root + "Document_СчетНаОплатуПокупателю(guid'" + ref + "')"
	auth := func(req *http.Request) {
		if username, _ := cfg["username"].(string); username != "" {
			password, _ := cfg["password"].(string)
			req.SetBasicAuth(username, password)
		}
	}
	get := func() map[string]any {
		for attempt := 0; attempt < 4; attempt++ {
			req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, entity+"?$format=json", nil)
			if err != nil {
				t.Fatal(err)
			}
			auth(req)
			resp, err := client.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			if resp.StatusCode == 200 {
				var data map[string]any
				err = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&data)
				resp.Body.Close()
				if err != nil {
					t.Fatal(err)
				}
				if nested, ok := data["d"].(map[string]any); ok {
					return nested
				}
				return data
			}
			resp.Body.Close()
			if resp.StatusCode != 400 && resp.StatusCode != 500 || attempt == 3 {
				t.Fatalf("1C invoice GET status %d", resp.StatusCode)
			}
			time.Sleep(25 * time.Second)
		}
		return nil
	}
	if before := get(); before["DeletionMark"] != false || before["Posted"] != true {
		t.Fatal("test invoice is no longer posted and active")
	}
	unpost, err := http.NewRequestWithContext(context.Background(), http.MethodPost, entity+"/Unpost?PostingModeOperational=false", nil)
	if err != nil {
		t.Fatal(err)
	}
	auth(unpost)
	resp, err := client.Do(unpost)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 200 && resp.StatusCode != 204 {
		t.Fatalf("1C invoice Unpost status %d", resp.StatusCode)
	}
	version, _ := get()["DataVersion"].(string)
	if version == "" {
		t.Fatal("1C invoice DataVersion missing")
	}
	patchOnce := func(version string) (int, []byte) {
		patch, err := http.NewRequestWithContext(context.Background(), http.MethodPatch, entity+"?$format=json", strings.NewReader(`{"DeletionMark":true}`))
		if err != nil {
			t.Fatal(err)
		}
		patch.Header.Set("Content-Type", "application/json; charset=utf-8")
		patch.Header.Set("If-Match", `"`+version+`"`)
		auth(patch)
		resp, err := client.Do(patch)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return resp.StatusCode, body
	}
	var code int
	var body []byte
	for attempt := 0; attempt < 4; attempt++ {
		code, body = patchOnce(version)
		if code != 400 && code != 500 || attempt == 3 {
			break
		}
		time.Sleep(25 * time.Second)
		version, _ = get()["DataVersion"].(string)
	}
	if code != 200 && code != 204 {
		var issue struct {
			Error struct {
				Message struct {
					Value string `json:"value"`
				} `json:"message"`
			} `json:"odata.error"`
		}
		_ = json.Unmarshal(body, &issue)
		reason := issue.Error.Message.Value
		if len(reason) > 250 {
			reason = reason[:250]
		}
		t.Fatalf("1C invoice cancellation PATCH status %d: %s", code, reason)
	}
	if after := get(); after["DeletionMark"] != true {
		t.Fatal("1C invoice cancellation not visible through OData")
	}
}
