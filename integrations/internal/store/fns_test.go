package store

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fnsregistry"
)

func TestRegistryPostgresVersionsIsolationAndRestart(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	db, e := OpenPostgres(ctx, dsn)
	if e != nil {
		t.Fatal(e)
	}
	company := fmt.Sprintf("fns-test-%d", time.Now().UnixNano())
	r := fnsregistry.Record{INN: "9723161623", OGRN: "1234567890127", Name: "Первая", EntityType: "LEGAL_ENTITY", Source: "FNS_EGRUL", SourceFormat: "XML", ActualAt: "2026-10-20", RegistrationStatus: "ACTIVE", SignatureStatus: "NOT_VERIFIED", RetrievedAt: time.Now().UTC().Format(time.RFC3339)}
	saved, status, e := db.SaveRegistry(ctx, company, r)
	if e != nil || status != "updated" || saved.Version != 1 {
		t.Fatalf("save: %+v %s %v", saved, status, e)
	}
	_, status, e = db.SaveRegistry(ctx, company, r)
	if e != nil || status != "duplicate" {
		t.Fatalf("duplicate: %s %v", status, e)
	}
	r.Name = "Вторая"
	r.ActualAt = "2026-10-21"
	saved, status, e = db.SaveRegistry(ctx, company, r)
	if e != nil || status != "updated" || saved.Version != 2 {
		t.Fatalf("update: %+v %s %v", saved, status, e)
	}
	r.Name = "Старая"
	r.ActualAt = "2026-10-19"
	_, status, e = db.SaveRegistry(ctx, company, r)
	if e != nil || status != "outdated" {
		t.Fatalf("old: %s %v", status, e)
	}
	if x, e := db.GetRegistry(ctx, company+"-other", r.INN); e != nil || len(x) != 0 {
		t.Fatalf("tenant leak: %+v %v", x, e)
	}
	db.Close()
	db, e = OpenPostgres(ctx, dsn)
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	current, e := db.GetRegistry(ctx, company, r.INN)
	if e != nil || len(current) != 1 || current[0].Name != "Вторая" {
		t.Fatalf("reopened: %+v %v", current, e)
	}
	history, e := db.RegistryHistory(ctx, company, r.OGRN)
	if e != nil || len(history) != 2 {
		t.Fatalf("history: %+v %v", history, e)
	}
}
