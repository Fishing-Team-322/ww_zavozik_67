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
	entry := MarketplaceEntry{ExternalID: "report-1", SourceKind: "wildberries_finance", Category: "sale", AmountKopecks: 10000, Currency: "RUB", ObservedAt: "2026-10-24T00:00:00Z", DataMode: "mock"}
	changed, duplicates, err := p.SaveMarketplace(company, []MarketplaceEntry{entry})
	if err != nil || changed != 1 || duplicates != 0 {
		t.Fatalf("marketplace first: %d %d %v", changed, duplicates, err)
	}
	changed, duplicates, err = p.SaveMarketplace(company, []MarketplaceEntry{entry})
	if err != nil || changed != 0 || duplicates != 1 {
		t.Fatalf("marketplace duplicate: %d %d %v", changed, duplicates, err)
	}
	entry.AmountKopecks = 9000
	changed, duplicates, err = p.SaveMarketplace(company, []MarketplaceEntry{entry})
	if err != nil || changed != 1 || duplicates != 0 {
		t.Fatalf("marketplace correction: %d %d %v", changed, duplicates, err)
	}
	stored, err := p.GetMarketplace(company)
	if err != nil || len(stored) != 1 || stored[0].Version != 2 || stored[0].AmountKopecks != 9000 {
		t.Fatalf("marketplace stored: %+v %v", stored, err)
	}
	risk := RiskSignal{ExternalID: "debt-1", SourceKind: "fns_debt_snapshot", SubjectINN: "9723161623", Kind: "tax", AmountKopecks: 663436, DatasetAsOf: "2026-09-01", PublishedAt: "2026-09-25", RetrievedAt: "2026-10-24T00:00:00Z", SourceURL: "https://www.nalog.gov.ru/opendata/7707329152-debtam/", DataMode: "import"}
	changed, duplicates, err = p.SaveRisks(company, []RiskSignal{risk})
	if err != nil || changed != 1 || duplicates != 0 {
		t.Fatalf("risk first: %d %d %v", changed, duplicates, err)
	}
	changed, duplicates, err = p.SaveRisks(company, []RiskSignal{risk})
	if err != nil || changed != 0 || duplicates != 1 {
		t.Fatalf("risk duplicate: %d %d %v", changed, duplicates, err)
	}
	risk.AmountKopecks = 663437
	changed, duplicates, err = p.SaveRisks(company, []RiskSignal{risk})
	if err != nil || changed != 1 || duplicates != 0 {
		t.Fatalf("risk correction: %d %d %v", changed, duplicates, err)
	}
	risks, err := p.GetRisks(company)
	if err != nil || len(risks) != 1 || risks[0].Version != 2 || risks[0].AmountKopecks != 663437 {
		t.Fatalf("risk stored: %+v %v", risks, err)
	}
	party := Counterparty{ExternalID: "9723161623", SourceKind: "dadata", INN: "9723161623", OGRN: "1234567890123", Name: "Test LLC", Type: "LEGAL", Status: "ACTIVE", CheckedAt: "2026-10-24T00:00:00Z", SourceURL: "https://dadata.ru/api/find-party/", DataMode: "mock"}
	firstParty, err := p.SaveCounterparty(company, party)
	if err != nil || firstParty.Version != 1 {
		t.Fatalf("counterparty first: %+v %v", firstParty, err)
	}
	party.Name = "Changed LLC"
	changedParty, err := p.SaveCounterparty(company, party)
	if err != nil || changedParty.Version != 2 {
		t.Fatalf("counterparty correction: %+v %v", changedParty, err)
	}
	parties, err := p.GetCounterparties(company)
	if err != nil || len(parties) != 1 || parties[0].Name != "Changed LLC" {
		t.Fatalf("counterparty stored: %+v %v", parties, err)
	}
}
