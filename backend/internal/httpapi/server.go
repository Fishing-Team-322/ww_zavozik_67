package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

var ErrNotImplemented = errors.New("not implemented")

// Server реализует StrictServerInterface. Новый эндпоинт: метод на Server
// с той же сигнатурой, что в Unimplemented.
type Server struct {
	Unimplemented

	ML       forecast.StochasticForecaster // nil, если ML не настроен
	Fallback forecast.StochasticForecaster
	Log      *slog.Logger
}

var _ StrictServerInterface = (*Server)(nil)

// Handler — готовый http.Handler со всеми маршрутами контракта.
func (s *Server) Handler() http.Handler {
	strict := NewStrictHandlerWithOptions(s, nil, StrictHTTPServerOptions{
		RequestErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		},
		ResponseErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			if errors.Is(err, ErrNotImplemented) {
				writeError(w, http.StatusNotImplemented, "not_implemented", "Эндпоинт ещё не реализован")
				return
			}
			s.Log.Error("handler failed", "method", r.Method, "path", r.URL.Path, "err", err)
			writeError(w, http.StatusInternalServerError, "internal", "Внутренняя ошибка")
		},
	})
	return HandlerWithOptions(strict, StdHTTPServerOptions{
		BaseRouter: http.NewServeMux(),
		ErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		},
	})
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
