// Command worker — фоновые задачи: разбор загрузок, синк источников,
// пересчёт прогноза, оценка алертов. Владелец: Бэк 3.
//
// TODO(Бэк 3): River (очередь в Postgres), цепочка
// ingest → recompute_forecast → evaluate_alerts → notify.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/config"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/logging"
)

func main() {
	cfg := config.Load()
	log := logging.New(cfg.LogLevel)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	log.Info("worker started (no jobs registered yet)")
	<-ctx.Done()
	log.Info("worker stopped")
}
