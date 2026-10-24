package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
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
	ML       forecast.StochasticForecaster // nil, если ML не настроен
	Fallback forecast.StochasticForecaster
	Log      *slog.Logger
	Accounts *platform.Service
	Products *product.Service
}

var _ StrictServerInterface = (*Server)(nil)

// Handler — готовый http.Handler со всеми маршрутами контракта.
func (s *Server) Handler() http.Handler {
	s.initProduct()
	mux := http.NewServeMux()
	strict := NewStrictHandlerWithOptions(s, nil, StrictHTTPServerOptions{
		RequestErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		},
		ResponseErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
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
			writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		},
	})
	return s.withPlatform(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
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
