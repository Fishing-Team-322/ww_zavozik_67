// Command api — HTTP API для фронта (контракт: api/openapi.yaml).
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/config"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/logging"
)

func main() {
	cfg := config.Load()
	log := logging.New(cfg.LogLevel)

	srv := &httpapi.Server{Fallback: forecast.SeasonalNaive{}, Log: log}
	if cfg.MLAddr != "" {
		ml, err := forecast.DialML(cfg.MLAddr)
		if err != nil {
			log.Error("ml client", "err", err)
			os.Exit(1)
		}
		defer ml.Close()
		srv.ML = ml
	}

	httpSrv := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           withMiddleware(srv.Handler(), log),
		ReadHeaderTimeout: 10 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		log.Info("api listening", "addr", cfg.HTTPAddr, "ml_addr", cfg.MLAddr)
		if err := httpSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("listen", "err", err)
			stop()
		}
	}()
	<-ctx.Done()

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(shutdownCtx)
	log.Info("api stopped")
}

// withMiddleware — recover и лог запросов. В лог идут только метод, путь,
// статус и время: тела запросов и query-параметры не пишем.
func withMiddleware(next http.Handler, log *slog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		defer func() {
			if p := recover(); p != nil {
				log.Error("panic", "path", r.URL.Path, "panic", p)
				http.Error(rec, `{"code":"internal","message":"Внутренняя ошибка"}`, http.StatusInternalServerError)
			}
			log.Info("http", "method", r.Method, "path", r.URL.Path, "status", rec.status, "dur_ms", time.Since(start).Milliseconds())
		}()
		next.ServeHTTP(rec, r)
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}
