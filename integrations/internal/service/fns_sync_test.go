package service

import (
	"archive/zip"
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestFNSSyncIdempotencyAndFailurePreservesSnapshot(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	db, e := store.OpenPostgres(ctx, dsn)
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	company := fmt.Sprintf("sync-test-%d", time.Now().UnixNano())
	var archive bytes.Buffer
	z := zip.NewWriter(&archive)
	w, e := z.Create("sample.xml")
	if e != nil {
		t.Fatal(e)
	}
	_, _ = w.Write([]byte(`<Файл><Документ ИдДок="x" ДатаДок="25.09.2026" ДатаСост="01.09.2026"><СведНП ИННЮЛ="9723161623"/><СведНедоим НаимНалог="Налог" ОбщСумНедоим="1.01"/></Документ></Файл>`))
	_ = z.Close()
	page := `<td>https://file.nalog.ru/opendata/7707329152-debtam/data-20260925-structure-20181201.zip</td><td>Данные на 01.09.2026</td>`
	downloads := 0
	fail := false
	client := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		var content []byte
		status := 200
		if fail {
			status = 503
		} else if strings.Contains(r.URL.Host, "file.nalog.ru") {
			downloads++
			content = archive.Bytes()
		} else {
			content = []byte(page)
		}
		return &http.Response{StatusCode: status, Body: io.NopCloser(bytes.NewReader(content)), ContentLength: int64(len(content)), Header: make(http.Header), Request: r}, nil
	})}
	s := FNSSync{DB: db, Client: client, PageURL: "https://www.nalog.gov.ru/opendata/7707329152-debtam/", CompanyID: company, INNs: []string{"9723161623"}}
	first, e := s.Run(ctx)
	if e != nil || first.Status != "updated" || first.Summary.Matches != 1 || downloads != 1 {
		t.Fatalf("first: %+v %v downloads=%d", first, e, downloads)
	}
	second, e := s.Run(ctx)
	if e != nil || second.Status != "unchanged" || downloads != 1 {
		t.Fatalf("repeat: %+v %v downloads=%d", second, e, downloads)
	}
	fail = true
	if _, e = s.Run(ctx); e == nil {
		t.Fatal("unavailable source accepted")
	}
	state, e := db.GetDatasetState(ctx, company)
	if e != nil || state.Publication.Version != "20260925-20181201" {
		t.Fatalf("snapshot lost: %+v %v", state, e)
	}
}
