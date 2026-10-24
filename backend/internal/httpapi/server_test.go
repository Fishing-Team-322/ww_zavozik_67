package httpapi

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func testServer() *Server {
	return &Server{Fallback: forecast.SeasonalNaive{}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
}

func get(t *testing.T, path string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	testServer().Handler().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	return rec
}

func TestHealthz(t *testing.T) {
	rec := get(t, "/healthz")
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body)
	}
	var h Health
	if err := json.Unmarshal(rec.Body.Bytes(), &h); err != nil {
		t.Fatal(err)
	}
	if h.Status != HealthStatusOk || h.Ml != HealthMlUnavailable {
		t.Errorf("got %+v", h)
	}
}

func TestListModelsIncludesBuiltin(t *testing.T) {
	rec := get(t, "/v1/models")
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body)
	}
	var models []ModelInfo
	if err := json.Unmarshal(rec.Body.Bytes(), &models); err != nil {
		t.Fatal(err)
	}
	for _, m := range models {
		if m.Name == forecast.NaiveName {
			return
		}
	}
	t.Errorf("builtin model missing from %+v", models)
}

// Ещё не реализованный эндпоинт остаётся заглушкой 501.
func TestUnimplementedRoute(t *testing.T) {
	if rec := get(t, "/v1/companies"); rec.Code != http.StatusNotImplemented {
		t.Fatalf("status %d: %s", rec.Code, rec.Body)
	}
}
