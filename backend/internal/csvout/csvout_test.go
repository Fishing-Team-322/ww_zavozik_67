package csvout

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWritesRecords(t *testing.T) {
	path := filepath.Join(t.TempDir(), "out.csv")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	w := New(f)
	w.Write([]string{"company_id", "date"})
	w.Write([]string{"C001", "2024-10-01"})
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if want := "company_id,date\nC001,2024-10-01\n"; string(got) != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

// /dev/full принимает open, но любая запись заканчивается ENOSPC. Строка
// помещается в буфер csv.Writer, поэтому ошибка обязана всплыть в Close.
func TestCloseReportsBufferedWriteFailure(t *testing.T) {
	f, err := os.OpenFile("/dev/full", os.O_WRONLY, 0)
	if err != nil {
		t.Skipf("/dev/full недоступен: %v", err)
	}
	w := New(f)
	w.Write([]string{"company_id", "date"})
	if err := w.Close(); err == nil {
		t.Fatal("Close must report the failed flush")
	}
}
