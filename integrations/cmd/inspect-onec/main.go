package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
)

func main() {
	baseURL := flag.String("url", "", "published 1C OData base URL")
	flag.Parse()
	client := onecodata.Client{Username: os.Getenv("ONEC_ODATA_USERNAME"), Password: os.Getenv("ONEC_ODATA_PASSWORD")}
	result, err := client.Inspect(context.Background(), *baseURL)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := json.NewEncoder(os.Stdout).Encode(result); err != nil {
		fmt.Fprintln(os.Stderr, "output failed")
		os.Exit(1)
	}
}
