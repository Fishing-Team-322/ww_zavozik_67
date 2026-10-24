package fns

import (
	"archive/zip"
	"bytes"
	"context"
	"strings"
	"testing"
	"time"
)

func archive(t *testing.T, xml string) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	w, err := zw.Create("sample.xml")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.Write([]byte(xml)); err != nil {
		t.Fatal(err)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func TestParseArchive(t *testing.T) {
	xml := `<?xml version="1.0"?><Файл><Документ ИдДок="doc1" ДатаДок="25.09.2026" ДатаСост="01.09.2026"><СведНП ИННЮЛ="9723161623"/><СведНедоим НаимНалог="Налог" ОбщСумНедоим="6634.36"/></Документ><Документ ИдДок="doc2" ДатаДок="25.09.2026" ДатаСост="01.09.2026"><СведНП ИННЮЛ="4706050392"/><СведНедоим НаимНалог="Пени" ОбщСумНедоим="1.01"/></Документ></Файл>`
	b := archive(t, xml)
	got, stats, err := ParseArchive(context.Background(), bytes.NewReader(b), int64(len(b)), map[string]struct{}{"9723161623": {}}, "https://file.nalog.ru/opendata/7707329152-debtam/test.zip", time.Date(2026, 10, 24, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if stats.Files != 1 || stats.Documents != 2 || stats.Matches != 1 || len(got) != 1 {
		t.Fatalf("stats=%+v got=%+v", stats, got)
	}
	if got[0].AmountKopecks != 663436 || got[0].DatasetAsOf != "2026-09-01" || got[0].DataMode != "import" {
		t.Fatalf("wrong dated amount: %+v", got[0])
	}
	got, stats, err = ParseArchive(context.Background(), bytes.NewReader(b), int64(len(b)), map[string]struct{}{"1111111111": {}}, "https://file.nalog.ru/opendata/7707329152-debtam/test.zip", time.Now())
	if err != nil || len(got) != 0 || stats.Documents != 2 {
		t.Fatalf("absence must be snapshot-only: %v %+v", err, stats)
	}
}

func TestRejectBadArchive(t *testing.T) {
	b := archive(t, `<Файл><Документ ИдДок="x" ДатаДок="25.09.2026" ДатаСост="01.09.2026"><СведНП ИННЮЛ="9723161623"/><СведНедоим НаимНалог="Tax" ОбщСумНедоим="1.001"/></Документ></Файл>`)
	_, _, err := ParseArchive(context.Background(), bytes.NewReader(b), int64(len(b)), map[string]struct{}{"9723161623": {}}, "https://file.nalog.ru/opendata/7707329152-debtam/test.zip", time.Now())
	if err == nil {
		t.Fatal("invalid kopecks accepted")
	}
	_, _, err = ParseArchive(context.Background(), bytes.NewReader(b), int64(len(b)), map[string]struct{}{"9723161623": {}}, "http://localhost/test.zip", time.Now())
	if err == nil {
		t.Fatal("untrusted source accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, _, err = ParseArchive(ctx, bytes.NewReader(b), int64(len(b)), map[string]struct{}{"9723161623": {}}, "https://file.nalog.ru/opendata/7707329152-debtam/test.zip", time.Now())
	if err != context.Canceled {
		t.Fatalf("cancellation: %v", err)
	}
	large := archive(t, strings.Repeat(" ", 17<<20))
	_, _, err = ParseArchive(context.Background(), bytes.NewReader(large), int64(len(large)), map[string]struct{}{"9723161623": {}}, "https://file.nalog.ru/opendata/7707329152-debtam/test.zip", time.Now())
	if err == nil {
		t.Fatal("oversized entry accepted")
	}
}
