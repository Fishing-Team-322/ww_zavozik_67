package onecodata_test

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/service"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func fixture(t *testing.T) onecodata.Config {
	t.Helper()
	cfg, err := onecodata.LoadConfig("../../../testdata/onec_odata_mock.json")
	if err != nil {
		t.Fatal(err)
	}
	return cfg
}

func TestFetchPaginationMappingAndRepeat(t *testing.T) {
	requests := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		u, p, ok := r.BasicAuth()
		if !ok || u != "reader" || p != "secret" {
			t.Error("missing Basic Auth")
		}
		if r.URL.Query().Get("$skiptoken") == "" && r.URL.Query().Get("$format") != "json" {
			t.Error("missing JSON format")
		}
		if strings.HasSuffix(r.URL.Path, "Document_BankReceipt") && r.URL.Query().Get("$skiptoken") == "" && r.URL.Query().Get("$expand") != "Counterparty" {
			t.Error("missing reference expansion")
		}
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "Document_BankReceipt") && r.URL.Query().Get("$skiptoken") == "":
			_, _ = w.Write([]byte(`{"d":{"results":[{"Ref_Key":"in-1","Number":"1","Date":"2026-10-20T10:00:00","ExecutionDate":"2026-10-20T11:00:00","Amount":1250.75,"Posted":true,"Account_Key":"bank-account-1","Counterparty":{"INN":"7800000000","Description":"  Покупатель  "},"PaymentPurpose":"Заказ  1"}],"__next":"?$skiptoken=page2"}}`))
		case strings.HasSuffix(r.URL.Path, "Document_BankReceipt"):
			_, _ = w.Write([]byte(`{"d":{"results":[{"Ref_Key":"in-1","Number":"1","Date":"2026-10-20","ExecutionDate":"2026-10-20","Amount":1250.75,"Posted":true,"Account_Key":"bank-account-1"},{"Ref_Key":"draft","Number":"2","Date":"2026-10-20","ExecutionDate":"2026-10-20","Amount":5,"Posted":false,"Account_Key":"bank-account-1"},{"Ref_Key":"other-account","Number":"3","Date":"2026-10-20","ExecutionDate":"2026-10-20","Amount":5,"Posted":true,"Account_Key":"unknown"}]}}`))
		case strings.HasSuffix(r.URL.Path, "Document_BankPayment"):
			_, _ = w.Write([]byte(`{"d":{"results":[{"Ref_Key":"out-1","Number":"4","Date":"2026-10-21","ExecutionDate":"2026-10-21","Amount":850.10,"Posted":true,"Unconfirmed":false,"Account_Key":"bank-account-1"},{"Ref_Key":"unconfirmed","Number":"5","Date":"2026-10-21","ExecutionDate":"2026-10-21","Amount":10,"Posted":true,"Unconfirmed":true,"Account_Key":"bank-account-1"}]}}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	cfg := fixture(t)
	cfg.BaseURL = srv.URL + "/odata/standard.odata/"
	cfg.Collections[0].Expand = []string{"Counterparty"}
	cfg.Collections[1].Fields.Unconfirmed = "Unconfirmed"
	importer := service.Importer{Store: store.NewMemory()}
	client := onecodata.Client{Username: "reader", Password: "secret"}
	first, err := importer.OneCOData(context.Background(), client, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if first.Stats.Parsed != 6 || first.Stats.Accepted != 2 || first.Stats.Duplicates != 1 || first.Stats.Rejected != 3 || len(first.Issues) != 3 || requests != 3 {
		t.Fatalf("batch: %+v, requests: %d", first.Stats, requests)
	}
	if first.Operations[0].AmountKopecks != 125075 || first.Operations[1].AmountKopecks != 85010 || first.Operations[0].CounterpartyName != "Покупатель" || first.Operations[0].Purpose != "Заказ 1" {
		t.Fatalf("operations: %+v", first.Operations)
	}
	if first.SourceKind != "onec_odata" || first.SourceMode != "pull" || first.ImportID == "" || first.ImportedAt == "" || first.Operations[0].ExternalID != "in-1" {
		t.Fatal("missing metadata")
	}
	second, err := importer.OneCOData(context.Background(), client, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if second.Stats.Accepted != 0 || second.Stats.Duplicates != 3 || second.Stats.Rejected != 3 {
		t.Fatalf("repeat: %+v", second.Stats)
	}
}

func TestUpstreamFailuresAndNoSecretLeak(t *testing.T) {
	cfg := fixture(t)
	secret := "PRIVATE_PASSWORD"
	for _, tc := range []struct {
		name    string
		handler http.HandlerFunc
		want    error
	}{
		{"auth", func(w http.ResponseWriter, _ *http.Request) { http.Error(w, secret, 401) }, onecodata.ErrAuth},
		{"malformed", func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte(`{"d":{"results":null}}`)) }, onecodata.ErrUpstream},
		{"too_large", func(w http.ResponseWriter, _ *http.Request) {
			_, _ = w.Write([]byte(`{"value":"` + strings.Repeat("x", 2<<20) + `"}`))
		}, onecodata.ErrLimit},
		{"redirect", func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Location", "https://example.org/")
			w.WriteHeader(302)
		}, onecodata.ErrUpstream},
		{"bad_next", func(w http.ResponseWriter, _ *http.Request) {
			_, _ = w.Write([]byte(`{"value":[],"@odata.nextLink":"https://example.org/steal"}`))
		}, onecodata.ErrUpstream},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(tc.handler)
			defer srv.Close()
			cfg.BaseURL = srv.URL + "/odata/standard.odata/"
			_, err := (onecodata.Client{Username: "reader", Password: secret}).Fetch(context.Background(), cfg)
			if !errors.Is(err, tc.want) || strings.Contains(err.Error(), secret) {
				t.Fatalf("err: %v", err)
			}
		})
	}
}

func TestFetchCounterpartyCatalog(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "Catalog_Counterparties"):
			if r.URL.Query().Get("$select") != "Ref_Key,INN,Description" {
				t.Error("missing catalog projection")
			}
			_, _ = w.Write([]byte(`{"value":[{"Ref_Key":"party-1","INN":"7800000000","Description":"  Покупатель  "}]}`))
		case strings.HasSuffix(r.URL.Path, "Document_BankReceipt"):
			_, _ = w.Write([]byte(`{"value":[{"Ref_Key":"in-1","Number":"1","Date":"2026-10-20","ExecutionDate":"2026-10-20","Amount":1250.75,"Posted":true,"Account_Key":"bank-account-1","Counterparty_Key":"party-1"}]}`))
		default:
			_, _ = w.Write([]byte(`{"value":[]}`))
		}
	}))
	defer srv.Close()
	cfg := fixture(t)
	cfg.BaseURL = srv.URL + "/odata/standard.odata/"
	cfg.Collections = cfg.Collections[:1]
	cfg.Collections[0].Fields.CounterpartyKey = "Counterparty_Key"
	cfg.Counterparties = &onecodata.ReferenceCatalog{EntitySet: "Catalog_Counterparties", Key: "Ref_Key", INN: "INN", Name: "Description"}
	batch, err := (onecodata.Client{}).Fetch(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Operations) != 1 || batch.Operations[0].CounterpartyINN != "7800000000" || batch.Operations[0].CounterpartyName != "Покупатель" {
		t.Fatalf("counterparty mapping: %+v", batch.Operations)
	}
}

func TestConfigValidation(t *testing.T) {
	cfg := fixture(t)
	cfg.BaseURL = "http://example.org/odata/"
	if !errors.Is(cfg.Validate(), onecodata.ErrConfig) {
		t.Fatal("plaintext remote URL accepted")
	}
	cfg = fixture(t)
	cfg.BaseURL = "https://user:secret@example.org/odata/"
	if !errors.Is(cfg.Validate(), onecodata.ErrConfig) {
		t.Fatal("URL credentials accepted")
	}
	cfg = fixture(t)
	cfg.Collections[0].EntitySet = "../other"
	if !errors.Is(cfg.Validate(), onecodata.ErrConfig) {
		t.Fatal("invalid entity accepted")
	}
	cfg = fixture(t)
	cfg.Counterparties = &onecodata.ReferenceCatalog{EntitySet: "../other", Key: "Ref_Key", INN: "INN", Name: "Description"}
	if !errors.Is(cfg.Validate(), onecodata.ErrConfig) {
		t.Fatal("invalid catalog accepted")
	}
	f, err := os.CreateTemp(t.TempDir(), "config-*.json")
	if err != nil {
		t.Fatal(err)
	}
	_ = json.NewEncoder(f).Encode(map[string]any{"base_url": "https://example.org/", "unexpected": "value"})
	_ = f.Close()
	if _, err = onecodata.LoadConfig(f.Name()); !errors.Is(err, onecodata.ErrConfig) {
		t.Fatal("unknown config key accepted")
	}
}
