package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/dadata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/ozon"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/wb"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/scheduler"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/service"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func main() {
	addr := os.Getenv("INTEGRATIONS_ADDR")
	if addr == "" {
		addr = "127.0.0.1:8091"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	postgres, err := store.OpenPostgres(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		log.Fatal("PostgreSQL unavailable or migration failed")
	}
	defer postgres.Close()
	companyID := os.Getenv("INTEGRATIONS_COMPANY_ID")
	if companyID == "" {
		companyID = "demo-company"
	}
	api := httpapi.API{Store: postgres, Ready: postgres.Ready, CompanyID: companyID, SyncToken: os.Getenv("INTEGRATIONS_SYNC_TOKEN")}
	if configPath := os.Getenv("ONEC_ODATA_CONFIG"); configPath != "" {
		cfg, err := onecodata.LoadConfig(configPath)
		if err != nil {
			log.Fatal("invalid OData configuration")
		}
		api.OneCConfig = &cfg
		api.OneCClient = onecodata.Client{Username: os.Getenv("ONEC_ODATA_USERNAME"), Password: os.Getenv("ONEC_ODATA_PASSWORD")}
	}
	if configPath := os.Getenv("ONEC_PLAN_CONFIG"); configPath != "" {
		cfg, err := onecodata.LoadPlanConfig(configPath)
		if err != nil {
			log.Fatal("invalid OData plan configuration")
		}
		api.OneCPlanConfig = &cfg
		api.OneCClient = onecodata.Client{Username: os.Getenv("ONEC_ODATA_USERNAME"), Password: os.Getenv("ONEC_ODATA_PASSWORD")}
	}
	if token := os.Getenv("DADATA_API_TOKEN"); token != "" {
		api.DaDataClient = &dadata.Client{Token: token, Cache: dadata.NewCache(24 * time.Hour)}
	}
	if token := os.Getenv("WB_API_TOKEN"); token != "" {
		api.WBClient = &wb.Client{Token: token}
	}
	if id, key := os.Getenv("OZON_CLIENT_ID"), os.Getenv("OZON_API_KEY"); id != "" && key != "" {
		api.OzonClient = &ozon.Client{ClientID: id, APIKey: key}
	}
	if api.SyncToken == "" {
		log.Fatal("missing sync token")
	}
	jobsCtx, jobsCancel := context.WithCancel(context.Background())
	defer jobsCancel()
	if setting := os.Getenv("ONEC_SYNC_INTERVAL"); setting != "" {
		interval, err := time.ParseDuration(setting)
		if err != nil || interval < time.Minute {
			log.Fatal("invalid sync interval")
		}
		if api.OneCConfig != nil {
			cfg := *api.OneCConfig
			scheduler.Run(jobsCtx, interval, 2*time.Minute, func(ctx context.Context) error {
				_, err := (service.Importer{Store: postgres}).OneCOData(ctx, api.OneCClient, cfg)
				status := 200
				if err != nil {
					status = 502
				}
				_ = postgres.RecordRun(cfg.CompanyID, "onec_odata", status)
				return err
			})
		}
		if api.OneCPlanConfig != nil {
			cfg := *api.OneCPlanConfig
			scheduler.Run(jobsCtx, interval, 2*time.Minute, func(ctx context.Context) error {
				_, err := (service.Importer{Store: postgres}).OneCPlans(ctx, api.OneCClient, cfg)
				status := 200
				if err != nil {
					status = 502
				}
				_ = postgres.RecordRun(cfg.CompanyID, "onec_plans", status)
				return err
			})
		}
	}
	srv := &http.Server{Addr: addr, Handler: api.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	log.Print("integration hub listening")
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-stop
		jobsCancel()
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = srv.Shutdown(ctx)
	}()
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal("server failed")
	}
}
