package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fns"
)

func main() {
	file := flag.String("file", "", "path to official FNS debt ZIP")
	inn := flag.String("inn", "", "10-digit legal entity INN to inspect")
	url := flag.String("url", "", "exact official FNS ZIP download URL")
	flag.Parse()
	if *file == "" || *inn == "" || *url == "" {
		fmt.Fprintln(os.Stderr, "--file, --inn and --url are required")
		os.Exit(2)
	}
	f, err := os.Open(*file)
	if err != nil {
		fmt.Fprintln(os.Stderr, "open archive:", err)
		os.Exit(1)
	}
	defer f.Close()
	stat, err := f.Stat()
	if err != nil {
		fmt.Fprintln(os.Stderr, "stat archive:", err)
		os.Exit(1)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	items, summary, err := fns.ParseArchive(ctx, f, stat.Size(), map[string]struct{}{*inn: {}}, *url, time.Now())
	if err != nil {
		fmt.Fprintln(os.Stderr, "inspect archive:", err)
		os.Exit(1)
	}
	_ = json.NewEncoder(os.Stdout).Encode(struct {
		Summary fns.Summary `json:"summary"`
		Items   []fns.Debt  `json:"items"`
	}{summary, items})
}
