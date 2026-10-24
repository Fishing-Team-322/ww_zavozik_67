package dadata_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/dadata"
)

func TestLookup(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.URL.Path != "/findById/party" || r.Header.Get("Authorization") != "Token secret" || r.Header.Get("Content-Type") != "application/json" {
			t.Error("invalid request")
		}
		buf := make([]byte, 256)
		n, _ := r.Body.Read(buf)
		if !strings.Contains(string(buf[:n]), `"query":"7707083893"`) || !strings.Contains(string(buf[:n]), `"branch_type":"MAIN"`) {
			t.Error("invalid query")
		}
		_, _ = w.Write([]byte(`{"suggestions":[{"data":{"inn":"7707083893","kpp":"773601001","ogrn":"1027700132195","name":{"short_with_opf":"ПАО СБЕРБАНК"},"state":{"status":"ACTIVE"},"address":{"value":"Москва"}}}]}`))
	}))
	defer srv.Close()
	party, err := (dadata.Client{Token: "secret", Endpoint: srv.URL + "/findById/party"}).Lookup(context.Background(), "7707083893")
	if err != nil || party.INN != "7707083893" || party.Name != "ПАО СБЕРБАНК" || party.Status != "ACTIVE" || party.SourceKind != "dadata" {
		t.Fatalf("party=%+v err=%v", party, err)
	}
}

func TestFailuresDoNotExposeTokenOrUpstreamBody(t *testing.T) {
	if _, err := (dadata.Client{Token: "secret"}).Lookup(context.Background(), "bad"); !errors.Is(err, dadata.ErrInvalidINN) {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name   string
		status int
		body   string
		want   error
	}{
		{"auth", 401, "SECRET_RESPONSE", dadata.ErrAuth},
		{"quota", 429, "SECRET_RESPONSE", dadata.ErrAuth},
		{"not_found", 200, `{"suggestions":[]}`, dadata.ErrNotFound},
		{"mismatch", 200, `{"suggestions":[{"data":{"inn":"9999999999"}}]}`, dadata.ErrUnavailable},
		{"malformed", 200, `{"suggestions":null}`, dadata.ErrUnavailable},
		{"redirect", 302, "SECRET_RESPONSE", dadata.ErrUnavailable},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Location", "https://example.org/")
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer srv.Close()
			_, err := (dadata.Client{Token: "secret", Endpoint: srv.URL}).Lookup(context.Background(), "7707083893")
			if !errors.Is(err, tc.want) || strings.Contains(err.Error(), "secret") || strings.Contains(err.Error(), "SECRET_RESPONSE") {
				t.Fatalf("error %v", err)
			}
		})
	}
}
