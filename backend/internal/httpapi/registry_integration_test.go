package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"mime/multipart"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestRegistryPreviewConfirmationAndIsolation(t *testing.T) {
	h := integration(t)
	owner, _ := h.register("registry-owner@example.invalid")
	other, _ := h.register("registry-other@example.invalid")
	r := h.call("POST", "/v1/companies", `{"name":"Registry workspace","legal_form":"ООО","industry":"tests","inn":"9723161623"}`, owner)
	status(t, r, 201)
	cid := decode[platform.Company](t, r).ID
	base := "/v1/companies/" + cid + "/registry"
	upload := func(content []byte, name, token string, want int) product.Doc {
		t.Helper()
		var body bytes.Buffer
		writer := multipart.NewWriter(&body)
		part, e := writer.CreateFormFile("file", name)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = part.Write(content); e != nil {
			t.Fatal(e)
		}
		if e = writer.Close(); e != nil {
			t.Fatal(e)
		}
		req := httptest.NewRequest("POST", base+"/preview", &body)
		req.Header.Set("Content-Type", writer.FormDataContentType())
		req.Header.Set("Authorization", "Bearer "+token)
		out := httptest.NewRecorder()
		h.handler.ServeHTTP(out, req)
		status(t, out, want)
		return decode[product.Doc](t, out)
	}
	xml := []byte(`<EGRUL ДатаВыг="2026-10-24"><СвЮЛ ИНН="9723161623" ОГРН="1234567890127" ДатаВып="2026-10-20"><СвНаимЮЛ НаимЮЛПолн="Synthetic registry fixture"/></СвЮЛ></EGRUL>`)
	upload(xml, "registry.xml", other, 404)
	upload([]byte("not a registry document"), "bad.pdf", owner, 422)
	preview := upload(xml, "registry.xml", owner, 200)
	confirm := func(preview product.Doc, target, token string, want int) product.Doc {
		t.Helper()
		body, _ := json.Marshal(product.Doc{"preview_id": preview["id"], "record_index": 0, "target": target})
		out := h.call("POST", base+"/confirm", string(body), token)
		status(t, out, want)
		return decode[product.Doc](t, out)
	}
	confirm(preview, "company", other, 404)
	saved := confirm(preview, "company", owner, 200)
	if saved["ownership_verified"] != false || saved["signature_status"] != "NOT_VERIFIED" {
		t.Fatal("registry overstated trust", saved)
	}
	if next := confirm(preview, "company", owner, 200); next["id"] != saved["id"] {
		t.Fatal("duplicate record")
	}
	list := h.call("GET", base, "", owner)
	status(t, list, 200)
	if len(decode[[]product.Doc](t, list)) != 1 {
		t.Fatal("duplicate history")
	}
	confirm(preview, "counterparty", owner, 200)
	parties := h.call("GET", "/v1/companies/"+cid+"/counterparties", "", owner)
	status(t, parties, 200)
	profiles := decode[[]product.Doc](t, parties)
	if len(profiles) != 1 || profiles[0]["registry"] == nil || profiles[0]["operations_count"] != float64(0) {
		t.Fatal("registry counterparty not available independently of bank operations", profiles)
	}
	lookup := h.call("GET", "/v1/fns/lookup?inn=9723161623", "", owner)
	status(t, lookup, 200)
	if decode[product.Doc](t, lookup)["ownership_verified"] != false {
		t.Fatal("lookup claimed ownership")
	}
	status(t, h.call("GET", "/v1/fns/lookup?inn=9723161623", "", other), 503)
	var ops int
	if e := h.db.Pool.QueryRow(context.Background(), "SELECT count(*) FROM operations WHERE company_id=$1", cid).Scan(&ops); e != nil || ops != 0 {
		t.Fatal("registry became bank facts", ops, e)
	}
	if filename := os.Getenv("LIVE_FNS_PDF"); filename != "" {
		data, e := os.ReadFile(filename)
		if e != nil {
			t.Fatal(e)
		}
		live := upload(data, "official-egrul.pdf", owner, 200)
		records := live["records"].([]any)
		rec := records[0].(map[string]any)
		if rec["inn"] != "6164138513" || rec["ogrn"] != "1226100018561" || rec["actual_at"] != "2026-10-24" {
			t.Fatal("official extract mismatch")
		}
		confirm(live, "company", owner, 409)
		confirm(live, "counterparty", owner, 200)
	}
}
