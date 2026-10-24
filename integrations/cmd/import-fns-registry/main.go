package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fnsregistry"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func main() {
	file := flag.String("file", "", "downloaded FNS EGRUL/EGRIP PDF, XML or ZIP")
	company := flag.String("company", "", "owning company ID")
	flag.Parse()
	if *file == "" || *company == "" {
		fmt.Fprintln(os.Stderr, "--file and --company are required")
		os.Exit(2)
	}
	f, err := os.Open(*file)
	if err != nil {
		fmt.Fprintln(os.Stderr, "cannot open file")
		os.Exit(1)
	}
	defer f.Close()
	stat, err := f.Stat()
	if err != nil || stat.Size() <= 0 || stat.Size() > fnsregistry.MaxUploadBytes {
		fmt.Fprintln(os.Stderr, "invalid file size")
		os.Exit(1)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	db, err := store.OpenPostgres(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		fmt.Fprintln(os.Stderr, "PostgreSQL unavailable")
		os.Exit(1)
	}
	defer db.Close()
	changed, duplicates, outdated := 0, 0, 0
	emit := func(r fnsregistry.Record) error {
		_, status, e := db.SaveRegistry(ctx, *company, r)
		if e != nil {
			return e
		}
		switch status {
		case "updated":
			changed++
		case "duplicate":
			duplicates++
		case "outdated":
			outdated++
		}
		return nil
	}
	name := strings.ToLower(*file)
	count := 0
	switch {
	case strings.HasSuffix(name, ".pdf"):
		r, e := fnsregistry.ParsePDF(f, stat.Size(), time.Now())
		if e != nil {
			err = e
		} else {
			count = 1
			err = emit(r)
		}
	case strings.HasSuffix(name, ".zip"):
		if _, err = fnsregistry.ParseZIP(ctx, f, stat.Size(), time.Now(), nil); err == nil {
			count, err = fnsregistry.ParseZIP(ctx, f, stat.Size(), time.Now(), emit)
		}
	case strings.HasSuffix(name, ".xml"):
		if _, err = fnsregistry.ParseXML(ctx, f, time.Now(), nil); err == nil {
			_, err = f.Seek(0, 0)
			if err == nil {
				count, err = fnsregistry.ParseXML(ctx, f, time.Now(), emit)
			}
		}
	default:
		err = fmt.Errorf("expected PDF, XML or ZIP")
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "registry import failed:", err)
		os.Exit(1)
	}
	_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"records": count, "changed": changed, "duplicates": duplicates, "outdated": outdated})
}
