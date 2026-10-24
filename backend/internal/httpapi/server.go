package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

var ErrNotImplemented = errors.New("not implemented")

// Server реализует StrictServerInterface. Новый эндпоинт: метод на Server
// с той же сигнатурой, что в Unimplemented.
type Server struct {
	ML                forecast.StochasticForecaster // nil, если ML не настроен
	Fallback          forecast.StochasticForecaster
	Log               *slog.Logger
	Accounts          *platform.Service
	Products          *product.Service
	TrustedProxyCIDRs []string
}

var _ StrictServerInterface = (*Server)(nil)

// Handler — готовый http.Handler со всеми маршрутами контракта.
func (s *Server) Handler() http.Handler {
	s.initProduct()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		if s.Products == nil || s.Products.DB == nil || s.Products.DB.Pool.Ping(ctx) != nil {
			writeError(w, 503, "not_ready", "Хранилище недоступно")
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "ready"})
	})
	revision := os.Getenv("APP_BUILD_SHA")
	strict := NewStrictHandlerWithOptions(s, nil, StrictHTTPServerOptions{
		RequestErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		},
		ResponseErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			if writeContextError(w, r.Context().Err()) || writeContextError(w, err) {
				return
			}
			var pe *platform.Error
			if errors.As(err, &pe) {
				s.platformError(w, err)
				return
			}
			if errors.Is(err, ErrNotImplemented) {
				writeError(w, http.StatusNotImplemented, "not_implemented", "Эндпоинт ещё не реализован")
				return
			}
			s.Log.Error("handler failed", "method", r.Method, "path", r.URL.Path)
			writeError(w, http.StatusInternalServerError, "internal", "Внутренняя ошибка")
		},
	})
	generated := HandlerWithOptions(strict, StdHTTPServerOptions{
		BaseRouter: mux,
		ErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			if strings.Contains(err.Error(), "counterparty_id") {
				writeError(w, http.StatusBadRequest, "invalid_counterparty_id", "Укажите корректный идентификатор контрагента или снимите фильтр")
				return
			}
			if strings.Contains(err.Error(), "unread") {
				writeError(w, http.StatusBadRequest, "invalid_unread", "Фильтр прочтения должен быть true или false; для всех уведомлений снимите фильтр")
				return
			}
			writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		},
	})
	return s.withPlatform(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if revision != "" {
			w.Header().Set("X-App-Revision", revision)
		}
		// Legacy links used empty optional filters. Empty means absent, never a UUID/boolean value.
		q := r.URL.Query()
		changed := false
		for _, name := range []string{"counterparty_id", "unread"} {
			if values, ok := q[name]; ok && len(values) == 1 && values[0] == "" {
				q.Del(name)
				changed = true
			}
		}
		if changed {
			r.URL.RawQuery = q.Encode()
		}
		_, pattern := mux.Handler(r)
		if pattern == "" {
			allowed := []string{}
			for _, method := range []string{"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"} {
				probe := r.Clone(r.Context())
				probe.Method = method
				if _, p := mux.Handler(probe); p != "" {
					allowed = append(allowed, method)
				}
			}
			if len(allowed) > 0 {
				w.Header().Set("Allow", strings.Join(allowed, ", "))
				writeError(w, 405, "method_not_allowed", "Метод не поддерживается")
			} else {
				writeError(w, 404, "not_found", "Эндпоинт не найден")
			}
			return
		}
		generated.ServeHTTP(w, r)
	}))
}

func writeContextError(w http.ResponseWriter, err error) bool {
	if errors.Is(err, context.Canceled) {
		writeError(w, 499, "request_cancelled", "Запрос отменён клиентом")
		return true
	}
	if errors.Is(err, context.DeadlineExceeded) {
		writeError(w, http.StatusGatewayTimeout, "request_timeout", "Время ожидания запроса истекло")
		return true
	}
	return false
}

func writeError(w http.ResponseWriter, status int, code, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(Error{Code: code, Message: msg})
}

func (s *Server) GetHealth(ctx context.Context, _ GetHealthRequestObject) (GetHealthResponseObject, error) {
	h := Health{Status: HealthStatusOk, Ml: HealthMlUnavailable}
	if s.ML != nil {
		ctx, cancel := context.WithTimeout(ctx, time.Second)
		defer cancel()
		if _, err := s.ML.Models(ctx); err == nil {
			h.Ml = HealthMlOk
		}
	}
	return GetHealth200JSONResponse(h), nil
}

func (s *Server) ListModels(ctx context.Context, _ ListModelsRequestObject) (ListModelsResponseObject, error) {
	var out []ModelInfo
	if s.ML != nil {
		ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
		defer cancel()
		models, err := s.ML.Models(ctx)
		if err != nil {
			s.Log.Warn("ml list models failed", "err", err)
		}
		for _, m := range models {
			out = append(out, ModelInfo{Name: m.Name, Description: m.Description, IsDefault: m.IsDefault})
		}
	}
	if s.Fallback != nil {
		models, _ := s.Fallback.Models(ctx)
		for _, m := range models {
			out = append(out, ModelInfo{Name: m.Name, Description: m.Description, IsDefault: len(out) == 0})
		}
	}
	return ListModels200JSONResponse(out), nil
}
