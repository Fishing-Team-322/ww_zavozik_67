package main

import (
	"context"
	"flag"
	"fmt"
	"os"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
)

// Reads a configured infobase without printing document IDs, counterparties,
// credentials or complete accounting rows.
func main() {
	configPath := flag.String("config", "", "path to a local 1C plan mapping JSON")
	flag.Parse()
	cfg, err := onecodata.LoadPlanConfig(*configPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "invalid 1C plan configuration")
		os.Exit(1)
	}
	batch, err := (onecodata.Client{Username: os.Getenv("ONEC_ODATA_USERNAME"), Password: os.Getenv("ONEC_ODATA_PASSWORD")}).FetchPlans(context.Background(), cfg)
	if err != nil {
		fmt.Fprintln(os.Stderr, "1C plan read failed:", err)
		os.Exit(1)
	}
	statuses := map[string]int{}
	issues := map[string]int{}
	for _, issue := range batch.Issues {
		issues[issue.Code]++
	}
	var total, paid, remaining int64
	for _, event := range batch.PlannedEvents {
		statuses[event.Status]++
		total += event.TotalKopecks
		paid += event.PaidKopecks
		remaining += event.RemainingKopecks
	}
	fmt.Printf("parsed=%d accepted=%d rejected=%d duplicates=%d statuses=%v issues=%v total_kopecks=%d paid_kopecks=%d remaining_kopecks=%d\n",
		batch.Stats.Parsed, batch.Stats.Accepted, batch.Stats.Rejected, batch.Stats.Duplicates, statuses, issues, total, paid, remaining)
}
