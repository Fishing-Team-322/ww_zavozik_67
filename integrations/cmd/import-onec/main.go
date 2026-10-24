package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/service"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	path := flag.String("file", "", "1CClientBankExchange file")
	companyID := flag.String("company-id", "", "company ID")
	inn := flag.String("company-inn", "", "company INN")
	account := flag.String("company-account", "", "company account")
	flag.Parse()
	id := contracts.Identity{CompanyID: *companyID, CompanyINN: *inn, CompanyAccount: *account}
	if err := id.Validate(); err != nil {
		return err
	}
	if *path == "" {
		return fmt.Errorf("--file is required")
	}
	f, err := os.Open(*path)
	if err != nil {
		return fmt.Errorf("cannot open file")
	}
	defer f.Close()
	batch, err := (service.Importer{}).OneCBank(context.Background(), f, id)
	if err != nil {
		return fmt.Errorf("import failed: %w", err)
	}
	return json.NewEncoder(os.Stdout).Encode(batch)
}
