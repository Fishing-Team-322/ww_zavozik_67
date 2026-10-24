package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/service"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func main() {
	company := flag.String("company", "", "owning Hub company ID")
	inns := flag.String("inns", "", "comma-separated 10-digit legal entity INNs")
	flag.Parse()
	if *company == "" || *inns == "" {
		fmt.Fprintln(os.Stderr, "--company and --inns are required")
		os.Exit(2)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	db, err := store.OpenPostgres(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		fmt.Fprintln(os.Stderr, "PostgreSQL unavailable")
		os.Exit(1)
	}
	defer db.Close()
	result, err := (service.FNSSync{DB: db, CompanyID: *company, INNs: strings.Split(*inns, ",")}).Run(ctx)
	if err != nil {
		fmt.Fprintln(os.Stderr, "FNS sync failed:", err)
		os.Exit(1)
	}
	_ = json.NewEncoder(os.Stdout).Encode(result)
}
