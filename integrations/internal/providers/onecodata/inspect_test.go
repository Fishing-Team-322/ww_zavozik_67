package onecodata_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
)

const sampleMetadata = `<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx"><edmx:DataServices><Schema xmlns="http://schemas.microsoft.com/ado/2009/11/edm" Namespace="StandardODATA"><EntityType Name="Catalog_Products"><Property Name="Ref_Key" Type="Edm.Guid"/><Property Name="Description" Type="Edm.String"/></EntityType><EntityContainer Name="Default"><EntitySet Name="Catalog_Products" EntityType="StandardODATA.Catalog_Products"/></EntityContainer></Schema></edmx:DataServices></edmx:Edmx>`

func TestInspectDiscoversFieldsWithoutRecords(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u, p, ok := r.BasicAuth()
		if !ok || u != "reader" || p != "secret" {
			t.Error("missing Basic Auth")
		}
		if strings.HasSuffix(r.URL.Path, "/$metadata") {
			_, _ = w.Write([]byte(sampleMetadata))
			return
		}
		_, _ = w.Write([]byte(`{"value":[{"name":"Catalog_Products","url":"Catalog_Products"}]}`))
	}))
	defer srv.Close()
	result, err := (onecodata.Client{Username: "reader", Password: "secret"}).Inspect(context.Background(), srv.URL+"/odata/standard.odata/")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Collections) != 1 || result.Collections[0].Name != "Catalog_Products" || len(result.Collections[0].Fields) != 2 || result.Collections[0].Fields[1].Name != "Description" {
		t.Fatalf("discovery: %+v", result)
	}
}

func TestInspectRejectsUnsafeURLAndUpstreamErrors(t *testing.T) {
	if _, err := (onecodata.Client{}).Inspect(context.Background(), "http://example.org/odata/"); !errors.Is(err, onecodata.ErrConfig) {
		t.Fatalf("insecure URL: %v", err)
	}
	secret := "PRIVATE_PASSWORD"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/redirect/" {
			http.Redirect(w, r, "https://example.org/", http.StatusFound)
			return
		}
		http.Error(w, secret, http.StatusUnauthorized)
	}))
	defer srv.Close()
	_, err := (onecodata.Client{Username: "reader", Password: secret}).Inspect(context.Background(), srv.URL+"/odata/")
	if !errors.Is(err, onecodata.ErrAuth) || strings.Contains(err.Error(), secret) {
		t.Fatalf("authentication error: %v", err)
	}
	_, err = (onecodata.Client{}).Inspect(context.Background(), srv.URL+"/redirect/")
	if !errors.Is(err, onecodata.ErrUpstream) {
		t.Fatalf("redirect: %v", err)
	}
}
