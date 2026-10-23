package forecast

import (
	"context"
	"net"
	"sync/atomic"
	"testing"
	"time"

	"google.golang.org/grpc"

	forecastv1 "github.com/Fishing-Team-322/ww_zavozik_67/backend/gen/forecast/v1"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// stubServer отдаёт ответ заданного размера, не глядя на запрос.
type stubServer struct {
	forecastv1.UnimplementedForecasterServiceServer
	paths int
	days  int
}

func (s stubServer) Forecast(context.Context, *forecastv1.ForecastRequest) (*forecastv1.ForecastResponse, error) {
	start := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	resp := &forecastv1.ForecastResponse{ModelUsed: "stub-model", Dates: make([]string, s.days)}
	for d := range resp.Dates {
		resp.Dates[d] = start.AddDate(0, 0, d+1).Format(domain.DateLayout)
	}
	resp.Paths = make([]*forecastv1.Path, s.paths)
	for p := range resp.Paths {
		in := make([]float64, s.days)
		out := make([]float64, s.days)
		for d := range in {
			in[d], out[d] = 100, 40
		}
		resp.Paths[p] = &forecastv1.Path{Inflow: in, Outflow: out}
	}
	return resp, nil
}

func startStub(t *testing.T, srv stubServer) string {
	t.Helper()
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	s := grpc.NewServer()
	forecastv1.RegisterForecasterServiceServer(s, srv)
	go func() { _ = s.Serve(lis) }()
	t.Cleanup(s.Stop)
	return lis.Addr().String()
}

// ML-сервис поддерживает до 5000 путей и 366 дней; такой ответ заметно
// больше дефолтных 4 МиБ, и клиент обязан его принять.
func TestMLClientReceivesLargeForecast(t *testing.T) {
	const paths, days = 5000, 90
	addr := startStub(t, stubServer{paths: paths, days: days})
	ml, err := DialML(addr)
	if err != nil {
		t.Fatal(err)
	}
	defer ml.Close()

	sf, err := ml.Forecast(context.Background(), StochasticRequest{Horizon: days, NPaths: paths})
	if err != nil {
		t.Fatal(err)
	}
	if sf.ModelUsed != "stub-model" || len(sf.Inflow) != paths || len(sf.Inflow[0]) != days {
		t.Fatalf("unexpected forecast: model %q, paths %d", sf.ModelUsed, len(sf.Inflow))
	}
}

// Сборка прогноза не должна молча подменять доступную ML-модель фолбэком.
func TestAssemblerKeepsPrimaryModelForLargeForecast(t *testing.T) {
	const paths, days = 5000, 90
	addr := startStub(t, stubServer{paths: paths, days: days})
	ml, err := DialML(addr)
	if err != nil {
		t.Fatal(err)
	}
	defer ml.Close()

	var fallbackCalls atomic.Int32
	a := Assembler{Primary: ml, Fallback: countingForecaster{calls: &fallbackCalls}}
	asOf := time.Date(2025, 6, 1, 0, 0, 0, 0, time.UTC)
	res, err := a.Build(context.Background(), Input{
		AsOf:           asOf,
		OpeningBalance: 1000,
		Stochastic:     StochasticRequest{Horizon: days, NPaths: paths},
	})
	if err != nil {
		t.Fatal(err)
	}
	if res.Stochastic.ModelUsed != "stub-model" {
		t.Fatalf("model %q: fallback used", res.Stochastic.ModelUsed)
	}
	if got := fallbackCalls.Load(); got != 0 {
		t.Fatalf("fallback called %d times", got)
	}
}

type countingForecaster struct{ calls *atomic.Int32 }

func (c countingForecaster) Forecast(ctx context.Context, req StochasticRequest) (StochasticForecast, error) {
	c.calls.Add(1)
	return SeasonalNaive{}.Forecast(ctx, req)
}

func (c countingForecaster) Models(context.Context) ([]ModelInfo, error) { return nil, nil }
