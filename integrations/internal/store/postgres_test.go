package store

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
)

func TestPostgresDurabilityAndCorrection(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}
	company := fmt.Sprintf("pg-test-%d", time.Now().UnixNano())
	ctx := context.Background()
	p, err := OpenPostgres(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	due := "2026-11-05"
	batch := contracts.NewBatchFor(company, "test_source", "fixture")
	batch.ImportID = "test-1"
	batch.Stats.Accepted = 2
	batch.Operations = []contracts.Operation{{ExternalID: "payment-1", DedupKey: "payment-1", Date: "2026-10-24", AmountKopecks: 10000, Direction: "in", SourceKind: "test_source", Executed: true}}
	batch.PlannedEvents = []contracts.PlannedEvent{{ExternalID: "invoice-1", Date: due, AmountKopecks: 25000, TotalKopecks: 35000, PaidKopecks: 10000, RemainingKopecks: 25000, Direction: "in", SourceKind: "test_source", Status: "partially_paid", DueDate: &due, Currency: "RUB", ForecastEligible: true}}
	first, err := p.Save(batch)
	if err != nil || first.Operations[0].Version != 1 || first.PlannedEvents[0].Version != 1 {
		t.Fatalf("first: %+v %v", first, err)
	}
	p.Close()
	p, err = OpenPostgres(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer p.Close()
	ops, err := p.GetOperations(company)
	if err != nil || len(ops) != 1 || ops[0].AmountKopecks != 10000 {
		t.Fatalf("reopen ops: %+v %v", ops, err)
	}
	plans, err := p.GetPlans(company)
	if err != nil || len(plans) != 1 || plans[0].AmountKopecks != 25000 {
		t.Fatalf("reopen plans: %+v %v", plans, err)
	}
	if other, _ := p.GetPlans(company + "-other"); len(other) != 0 {
		t.Fatalf("tenant leak: %+v", other)
	}
	batch.ImportID = "test-2"
	second, err := p.Save(batch)
	if err != nil || second.Stats.Duplicates != 2 || second.Stats.Accepted != 0 {
		t.Fatalf("duplicate: %+v %v", second.Stats, err)
	}
	batch.ImportID = "test-3"
	batch.Operations[0].AmountKopecks = 12000
	batch.PlannedEvents[0].AmountKopecks = 23000
	batch.PlannedEvents[0].RemainingKopecks = 23000
	third, err := p.Save(batch)
	if err != nil || third.Operations[0].Version != 2 || third.PlannedEvents[0].Version != 2 {
		t.Fatalf("correction: %+v %v", third, err)
	}
}
