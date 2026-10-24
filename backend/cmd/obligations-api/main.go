// Command obligations-api runs our own bank/accounting API for the prototype.
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/obligationapi"
)

func main() {
	api, e := obligationapi.New(os.Getenv("OBLIGATIONS_API_TOKEN"), os.Getenv("OBLIGATIONS_ADMIN_TOKEN"), os.Getenv("OBLIGATIONS_DATA_FILE"))
	if e != nil {
		log.Fatal("configure distinct OBLIGATIONS_API_TOKEN / OBLIGATIONS_ADMIN_TOKEN (32+ characters) and OBLIGATIONS_DATA_FILE in an existing directory")
	}
	addr := os.Getenv("OBLIGATIONS_HTTP_ADDR")
	if addr == "" {
		addr = "127.0.0.1:8092"
	}
	server := &http.Server{Addr: addr, Handler: api.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 60 * time.Second}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Print("demonstration obligations API started")
	if e = server.ListenAndServe(); e != nil && e != http.ErrServerClosed {
		log.Fatal("obligations API unavailable")
	}
}
