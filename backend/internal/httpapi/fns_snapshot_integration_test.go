package httpapi_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestFNSSnapshotFiltersSubjectsAndMissingPublication(t *testing.T) {
	h := integration(t)
	owner, _ := h.register("fns-snapshot@example.invalid")
	other, _ := h.register("fns-snapshot-other@example.invalid")
	snapshot := false
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer private-hub-token" {
			w.WriteHeader(401)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/v1/fns/opendata/status":
			if snapshot {
				w.Write([]byte(`{"last_success":{"company_id":"private-hub-tenant","retrieved_at":"2026-10-24T10:00:00Z","publication":{"dataset_as_of":"2026-10-01"}},"runs":[{"status":"done","company_id":"private-hub-tenant","error":"private-hub-token"}]}`))
			} else {
				w.Write([]byte(`{"last_success":{},"runs":[]}`))
			}
		case "/v1/risk-signals/operator":
			w.Write([]byte(`{"risk_signals":[{"subject_inn":"6164138513","kind":"tax_debt"},{"subject_inn":"7707083893","kind":"tax_debt"}]}`))
		default:
			w.WriteHeader(404)
		}
	}))
	defer hub.Close()
	service := &product.Service{DB: h.db, FNSHubURL: hub.URL, FNSHubToken: "private-hub-token", FNSHubCompany: "operator"}
	h.handler = (&httpapi.Server{Accounts: h.service, Products: service, Log: testLogger()}).Handler()
	created := h.call("POST", "/v1/companies", `{"name":"FNS isolated","inn":"6164138513","legal_form":"ООО","industry":"tests"}`, owner)
	status(t, created, 201)
	cid := decode[platform.Company](t, created).ID
	path := "/v1/companies/" + cid + "/fns-open-data"
	status(t, h.call("GET", path, "", other), 404)
	missing := h.call("GET", path, "", owner)
	status(t, missing, 200)
	if decode[product.Doc](t, missing)["status"] != "no_snapshot" {
		t.Fatal("missing snapshot reported as available")
	}
	snapshot = true
	result := h.call("GET", path, "", owner)
	status(t, result, 200)
	raw := result.Body.String()
	if strings.Contains(raw, "private-hub") || strings.Contains(raw, "7707083893") {
		t.Fatal("Hub secret or unrelated tenant data exposed")
	}
	d := decode[product.Doc](t, result)
	if d["status"] != "snapshot_available" || len(d["signals"].([]any)) != 1 || d["bank_fact"] != false {
		t.Fatal("wrong snapshot scope", d)
	}
	var n int
	if e := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM operations WHERE company_id=$1", cid).Scan(&n); e != nil || n != 0 {
		t.Fatal("risk signal became bank fact", n, e)
	}
}
