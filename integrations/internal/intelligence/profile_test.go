package intelligence

import (
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fnsregistry"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func TestOfficialPriorityConflictAndFreshness(t *testing.T) {
	now := time.Date(2026, 10, 24, 0, 0, 0, 0, time.UTC)
	reg := fnsregistry.Record{INN: "9723161623", OGRN: "1234567890123", Name: "Новое имя", ActualAt: "2026-10-20", Source: "FNS_EGRUL", EntityType: "LEGAL_ENTITY", RegistrationStatus: "TERMINATED"}
	d := store.Counterparty{INN: reg.INN, OGRN: reg.OGRN, Name: "Старое имя", Status: "ACTIVE", CheckedAt: "2026-10-19"}
	risk := store.RiskSignal{SubjectINN: reg.INN, Kind: "published_debt", DatasetAsOf: "2026-09-01"}
	p := Build(reg.INN, []fnsregistry.Record{reg}, []store.Counterparty{d}, []store.RiskSignal{risk}, now)
	if p.Name != "Новое имя" || p.RegistrationStatus != "TERMINATED" || len(p.Conflicts) < 2 || len(p.RiskSignals) != 1 {
		t.Fatalf("merge: %+v", p)
	}
	reg.ActualAt = "2025-01-01"
	p = Build(reg.INN, []fnsregistry.Record{reg}, nil, nil, now)
	if p.Status != "STALE" {
		t.Fatalf("stale: %+v", p)
	}
	p = Build(reg.INN, nil, nil, nil, now)
	if p.Status != "NOT_FOUND" {
		t.Fatalf("missing: %+v", p)
	}
}
