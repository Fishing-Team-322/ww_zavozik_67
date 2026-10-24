package fns

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestDiscoverDebt(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`<table><tr><td>Гиперссылка (URL) на набор</td><td>https://file.nalog.ru/opendata/7707329152-debtam/data-20260925-structure-20181201.zip</td></tr><tr><td>Содержание последнего изменения</td><td>Данные на 01.09.2026</td></tr></table>`))
	}))
	defer srv.Close()
	p, e := DiscoverDebt(context.Background(), srv.Client(), srv.URL)
	if e != nil || p.Version != "20260925-20181201" || p.DatasetAsOf != "2026-09-01" {
		t.Fatalf("publication: %+v %v", p, e)
	}
}
func TestDiscoverDebtRejectsUnknownLink(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`https://evil.example/data.zip Данные на 01.09.2026`))
	}))
	defer srv.Close()
	if _, e := DiscoverDebt(context.Background(), srv.Client(), srv.URL); e == nil {
		t.Fatal("unknown link accepted")
	}
}
