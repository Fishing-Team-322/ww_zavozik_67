package main

import (
	"errors"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/dadata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func main() {
	addr := os.Getenv("INTEGRATIONS_ADDR")
	if addr == "" {
		addr = "127.0.0.1:8091"
	}
	api := httpapi.API{Store: store.NewMemory(), SyncToken: os.Getenv("INTEGRATIONS_SYNC_TOKEN")}
	if configPath := os.Getenv("ONEC_ODATA_CONFIG"); configPath != "" {
		cfg, err := onecodata.LoadConfig(configPath)
		if err != nil {
			log.Fatal("invalid OData configuration")
		}
		api.OneCConfig = &cfg
		api.OneCClient = onecodata.Client{Username: os.Getenv("ONEC_ODATA_USERNAME"), Password: os.Getenv("ONEC_ODATA_PASSWORD")}
	}
	if token := os.Getenv("DADATA_API_TOKEN"); token != "" {
		api.DaDataClient = &dadata.Client{Token: token}
	}
	if api.SyncToken == "" {
		log.Fatal("missing sync token")
	}
	srv := &http.Server{Addr: addr, Handler: api.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	log.Print("integration hub listening")
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal("server failed")
	}
}
