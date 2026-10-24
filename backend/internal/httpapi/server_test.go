package httpapi

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func TestCancelledRequestsAreNotInternalServerErrors(t *testing.T) {
	for _, tc := range []struct {
		err    error
		status int
	}{{context.Canceled, 499}, {context.DeadlineExceeded, 504}} {
		w := httptest.NewRecorder()
		if !writeContextError(w, tc.err) || w.Code != tc.status {
			t.Fatalf("context error: status %d, want %d", w.Code, tc.status)
		}
	}
}

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

// Public quality works even when the optional reports are not mounted.
func TestModelQualityRoute(t *testing.T) {
	if rec := get(t, "/v1/models/quality"); rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body)
	}
}
