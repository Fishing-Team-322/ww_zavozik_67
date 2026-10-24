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
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

func main() {
	cfg := config.Load()
	log := logging.New(cfg.LogLevel)

	srv := &httpapi.Server{Fallback: forecast.SeasonalNaive{}, Log: log}
	if cfg.DatabaseURL != "" {
		if err := cfg.ValidatePlatform(); err != nil {
			log.Error("platform configuration", "err", err)
			os.Exit(1)
		}
		startup, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		db, err := store.Open(startup, cfg.DatabaseURL)
		cancel()
		if err != nil {
			log.Error("storage startup", "err", err)
			os.Exit(1)
		}
		defer db.Pool.Close()
		accounts, err := platform.New(db, cfg.JWTSecret)
		if err != nil {
			log.Error("account startup")
			os.Exit(1)
		}
		accounts.PublicURL = cfg.PublicURL
		accounts.Log = log
		accounts.FrontendURL = cfg.FrontendURL
		accounts.SecureCookies = cfg.CookieSecure
		accounts.Providers = platform.Providers(cfg.GoogleClientID, cfg.GoogleClientSecret, cfg.YandexClientID, cfg.YandexClientSecret, cfg.PublicURL)
		if cfg.SMTPAddr != "" {
			accounts.Mailer = platform.SMTPMailer{Addr: cfg.SMTPAddr, Username: cfg.SMTPUser, Password: cfg.SMTPPassword, From: cfg.SMTPFrom, LocalPlaintext: cfg.SMTPLocalPlaintext}
		}
		srv.Accounts = accounts
	} else {
		log.Warn("DATABASE_URL is empty; account and company APIs are unavailable")
	}
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
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	serveErr := make(chan error, 1)
	go func() {
		log.Info("api listening", "addr", cfg.HTTPAddr, "ml_addr", cfg.MLAddr)
		serveErr <- httpSrv.ListenAndServe()
	}()

	// Отказ ListenAndServe — это провал старта: после очистки выходим
	// ненулевым кодом, чтобы супервизор и smoke-тесты его заметили.
	var runErr error
	select {
	case <-ctx.Done():
	case err := <-serveErr:
		if !errors.Is(err, http.ErrServerClosed) {
			log.Error("listen", "err", err)
			runErr = err
		}
	}
	stop()

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := httpSrv.Shutdown(shutdownCtx); err != nil && runErr == nil {
		runErr = err
	}
	if runErr != nil {
		log.Error("api failed", "err", runErr)
		os.Exit(1)
	}
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
				log.Error("panic", "path", r.URL.Path)
				rec.Header().Set("Content-Type", "application/json")
				rec.WriteHeader(http.StatusInternalServerError)
				_, _ = rec.Write([]byte(`{"code":"internal","message":"Внутренняя ошибка"}`))
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
