// Command worker processes durable PostgreSQL import/sync/export/forecast jobs.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/config"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/logging"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

func main() {
	cfg := config.Load()
	log := logging.New(cfg.LogLevel)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if cfg.DatabaseURL == "" {
		log.Error("DATABASE_URL is required")
		os.Exit(1)
	}
	startup, cancel := context.WithTimeout(ctx, 10*time.Second)
	db, err := store.Open(startup, cfg.DatabaseURL)
	cancel()
	if err != nil {
		log.Error("worker storage unavailable")
		os.Exit(1)
	}
	defer db.Pool.Close()
	var model forecast.StochasticForecaster
	if cfg.MLAddr != "" {
		ml, e := forecast.DialML(cfg.MLAddr)
		if e != nil {
			log.Error("worker ML initialization failed")
			os.Exit(1)
		}
		defer ml.Close()
		model = ml
	}
	service, err := product.New(db, cfg, model)
	if err != nil {
		log.Error("worker configuration", "err", err)
		os.Exit(1)
	}
	if cfg.CategorizerMode == "qwen" {
		classifier, e := categorize.DialDiscovery(os.Getenv("ML_QWEN_ADDR"))
		if e != nil {
			log.Error("Qwen categorizer configuration failed")
			os.Exit(1)
		}
		defer classifier.Close()
		service.Categorizer = classifier
	} else if cfg.CategorizerMode == "hybrid" && cfg.MLAddr != "" {
		classifier, e := categorize.DialMLCategorizer(cfg.MLAddr)
		if e != nil {
			log.Error("worker categorizer initialization failed")
			os.Exit(1)
		}
		defer classifier.Close()
		service.Categorizer = categorize.Hybrid{Rules: categorize.DefaultRules, ML: classifier, MinMLConfidence: .8}
	} else if cfg.CategorizerMode != "rules" {
		log.Error("invalid CATEGORIZER_MODE")
		os.Exit(1)
	}
	log.Info("worker started")
	if err = service.Run(ctx); err != nil {
		log.Error("worker failed")
		os.Exit(1)
	}
	log.Info("worker stopped")
}
