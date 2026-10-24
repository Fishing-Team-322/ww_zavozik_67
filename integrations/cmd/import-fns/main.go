package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fns"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func main() {
	file := flag.String("file", "", "official FNS ZIP path")
	url := flag.String("url", "", "exact official FNS ZIP URL")
	inn := flag.String("inn", "", "10-digit company/counterparty INN")
	company := flag.String("company", "", "owning company ID in Hub")
	flag.Parse()
	if *file == "" || *url == "" || *inn == "" || *company == "" {
		fmt.Fprintln(os.Stderr, "--file, --url, --inn and --company are required")
		os.Exit(2)
	}
	f, err := os.Open(*file)
	if err != nil {
		fmt.Fprintln(os.Stderr, "cannot open FNS archive")
		os.Exit(1)
	}
	defer f.Close()
	stat, err := f.Stat()
	if err != nil {
		fmt.Fprintln(os.Stderr, "cannot stat FNS archive")
		os.Exit(1)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()
	items, summary, err := fns.ParseArchive(ctx, f, stat.Size(), map[string]struct{}{*inn: {}}, *url, time.Now())
	if err != nil {
		fmt.Fprintln(os.Stderr, "FNS archive import failed:", err)
		os.Exit(1)
	}
	db, err := store.OpenPostgres(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		fmt.Fprintln(os.Stderr, "PostgreSQL unavailable")
		os.Exit(1)
	}
	defer db.Close()
	signals := make([]store.RiskSignal, 0, len(items))
	for _, item := range items {
		sum := sha256.Sum256([]byte(item.DatasetAsOf + "\x00" + item.DocumentID + "\x00" + item.TaxName))
		signals = append(signals, store.RiskSignal{ExternalID: hex.EncodeToString(sum[:]), SourceKind: "fns_debt_snapshot", SubjectINN: item.INN, Kind: item.TaxName, AmountKopecks: item.AmountKopecks, DatasetAsOf: item.DatasetAsOf, PublishedAt: item.PublishedAt, RetrievedAt: item.RetrievedAt, SourceURL: item.SourceURL, DataMode: item.DataMode})
	}
	changed, duplicates, err := db.SaveRisks(*company, signals)
	if err != nil {
		fmt.Fprintln(os.Stderr, "cannot save FNS signals")
		os.Exit(1)
	}
	_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"files": summary.Files, "documents": summary.Documents, "matched": summary.Matches, "changed": changed, "duplicates": duplicates, "interpretation": "dated_public_snapshot_not_current_balance"})
}
