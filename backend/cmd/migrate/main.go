// Command migrate applies the embedded goose migrations before starting the API.
package main

import (
	"context"
	"database/sql"
	"log"
	"os"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/migrations"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
)

func main() {
	raw := os.Getenv("DATABASE_URL")
	if raw == "" {
		log.Fatal("DATABASE_URL is required")
	}
	db, err := sql.Open("pgx", raw)
	if err != nil {
		log.Fatal("database initialization failed")
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	if err = db.PingContext(ctx); err != nil {
		log.Fatal("database unavailable")
	}
	goose.SetBaseFS(migrations.Files)
	if err = goose.SetDialect("postgres"); err != nil {
		log.Fatal("migration dialect setup failed")
	}
	if err = goose.UpContext(ctx, db, "."); err != nil {
		log.Fatal("migration failed; inspect schema and migration versions")
	}
}
