package obligationapi

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/obligations"
)

func TestAPIReadOnlyAccessPersistenceAndAtomicFailures(t *testing.T) {
	read, admin := "read-token-with-at-least-32-characters", "admin-token-with-at-least-32-characters"
	path := filepath.Join(t.TempDir(), "snapshots.json")
	api, e := New(read, admin, path)
	if e != nil {
		t.Fatal(e)
	}
	feed := obligations.Feed{CompanyINN: "7707083893", AsOf: "2026-10-23", Complete: true, Items: []obligations.Item{{ExternalID: "loan-1/1", Kind: "loan_payment", Title: "Loan installment", DueDate: "2026-11-01", AmountKopecks: 100001, Direction: "out", Status: "expected"}}}
	call := func(api *API, method, token string, body any, want int) *httptest.ResponseRecorder {
		t.Helper()
		raw, _ := json.Marshal(body)
		r := httptest.NewRequest(method, "/v1/companies/7707083893/bank/obligations", bytes.NewReader(raw))
		r.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		api.Handler().ServeHTTP(w, r)
		if w.Code != want {
			t.Fatalf("status %d wanted %d: %s", w.Code, want, w.Body)
		}
		return w
	}
	call(api, "PUT", read, feed, 401)
	call(api, "GET", read, nil, 404)
	call(api, "PUT", admin, feed, 200)
	restarted, e := New(read, admin, path)
	if e != nil {
		t.Fatal(e)
	}
	var got obligations.Feed
	if e = json.Unmarshal(call(restarted, "GET", read, nil, 200).Body.Bytes(), &got); e != nil || got.DataMode != "demo" || len(got.Items) != 1 || got.Items[0].AmountKopecks != 100001 {
		t.Fatal(got, e)
	}
	feed.Items[0].AmountKopecks = 200002
	call(restarted, "PUT", admin, feed, 200)
	reloaded, e := New(read, admin, path)
	if e != nil {
		t.Fatal(e)
	}
	if e = json.Unmarshal(call(reloaded, "GET", read, nil, 200).Body.Bytes(), &got); e != nil || got.Items[0].AmountKopecks != 200002 {
		t.Fatal("updated snapshot was not persisted", got, e)
	}
	feed.CompanyINN = "7800000000"
	call(restarted, "PUT", admin, feed, 400)
	call(restarted, "GET", "wrong-token", nil, 401)
	feed.CompanyINN = "7707083893"
	feed.Complete = false
	call(restarted, "PUT", admin, feed, 400)
	if body := call(restarted, "GET", read, nil, 200).Body.String(); !bytes.Contains([]byte(body), []byte("loan-1/1")) {
		t.Fatal("bad writes destroyed snapshot", body)
	}
	// Failure to commit the file must not publish a new in-memory snapshot.
	broken, e := New(read, admin, filepath.Join(t.TempDir(), "missing-directory", "state.json"))
	if e != nil {
		t.Fatal(e)
	}
	feed.Complete = true
	call(broken, "PUT", admin, feed, 500)
	call(broken, "GET", read, nil, 404)
}
