package importcsv

import (
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
	"golang.org/x/text/encoding/charmap"
)

func TestPreviewAndIdempotentCommit(t *testing.T) {
	csv := "external_id;date;amount;direction;title;due_date\ninv-1;24.10.2026;350 000,00;in;Счёт;05.11.2026\ninv-2;bad;1;out;Ошибка;06.11.2026\n"
	preview, err := Parse(strings.NewReader(csv), "demo-company", Mapping{Category: "invoice"})
	if err != nil || preview.Batch.Stats.Accepted != 1 || preview.Batch.Stats.Rejected != 1 || len(preview.Issues) != 1 {
		t.Fatalf("preview=%+v err=%v", preview, err)
	}
	if preview.Batch.PlannedEvents[0].AmountKopecks != 35000000 || *preview.Batch.PlannedEvents[0].DueDate != "2026-11-05" {
		t.Fatalf("plan=%+v", preview.Batch.PlannedEvents[0])
	}
	s := store.NewMemory()
	first := s.Add(preview.Batch)
	second := s.Add(preview.Batch)
	if len(first.PlannedEvents) != 1 || len(second.PlannedEvents) != 0 || second.Stats.Duplicates != 1 {
		t.Fatalf("first=%+v second=%+v", first.Stats, second.Stats)
	}
	changed := strings.Replace(csv, "350 000,00", "250 000,00", 1)
	updated, err := Parse(strings.NewReader(changed), "demo-company", Mapping{Category: "invoice"})
	if err != nil {
		t.Fatal(err)
	}
	result := s.Add(updated.Batch)
	if len(result.PlannedEvents) != 1 || result.PlannedEvents[0].Version != 2 || result.PlannedEvents[0].AmountKopecks != 25000000 {
		t.Fatalf("update=%+v", result.PlannedEvents)
	}
}

func TestActualRequiresConfirmationAndCP1251(t *testing.T) {
	csv := "external_id;date;amount;direction;executed;title\nop1;2026-10-24;10.25;out;true;Оплата\nop2;2026-10-24;20;in;false;Не факт\n"
	b, err := charmap.Windows1251.NewEncoder().Bytes([]byte(csv))
	if err != nil {
		t.Fatal(err)
	}
	preview, err := Parse(strings.NewReader(string(b)), "demo-company", Mapping{Category: "actual", Encoding: "cp1251"})
	if err != nil || len(preview.Batch.Operations) != 1 || preview.Batch.Operations[0].AmountKopecks != 1025 || preview.Batch.Stats.Rejected != 1 {
		t.Fatalf("preview=%+v err=%v", preview, err)
	}
}

func TestMissingColumn(t *testing.T) {
	_, err := Parse(strings.NewReader("date;amount\n2026-10-24;10\n"), "demo-company", Mapping{Category: "actual"})
	if err == nil {
		t.Fatal("missing direction accepted")
	}
}
