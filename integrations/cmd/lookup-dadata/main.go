package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/dadata"
)

func main() {
	inn := flag.String("inn", "", "10- or 12-digit INN")
	id := flag.String("id", "", "INN or OGRN")
	flag.Parse()
	identifier := *id
	if identifier == "" {
		identifier = *inn
	}
	party, err := (dadata.Client{Token: os.Getenv("DADATA_API_TOKEN")}).Lookup(context.Background(), identifier)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := json.NewEncoder(os.Stdout).Encode(party); err != nil {
		fmt.Fprintln(os.Stderr, "output failed")
		os.Exit(1)
	}
}
