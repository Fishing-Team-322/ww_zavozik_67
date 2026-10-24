package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/service"
)

func main() {
	configPath := flag.String("config", "", "path to OData mapping JSON")
	flag.Parse()
	cfg, err := onecodata.LoadConfig(*configPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "invalid OData configuration")
		os.Exit(1)
	}
	client := onecodata.Client{Username: os.Getenv("ONEC_ODATA_USERNAME"), Password: os.Getenv("ONEC_ODATA_PASSWORD")}
	batch, err := (service.Importer{}).OneCOData(context.Background(), client, cfg)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := json.NewEncoder(os.Stdout).Encode(batch); err != nil {
		fmt.Fprintln(os.Stderr, "output failed")
		os.Exit(1)
	}
}
