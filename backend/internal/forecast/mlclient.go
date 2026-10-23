package forecast

import (
	"context"
	"fmt"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	forecastv1 "github.com/Fishing-Team-322/ww_zavozik_67/backend/gen/forecast/v1"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// MLClient — gRPC-клиент Python-сервиса (proto/forecast/v1).
type MLClient struct {
	conn *grpc.ClientConn
	c    forecastv1.ForecasterServiceClient
}

// DialML не ходит в сеть: соединение ленивое, сервис может подняться позже.
// Внутри docker-сети без TLS; наружу ML-сервис не публикуется.
func DialML(addr string) (*MLClient, error) {
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("ml: dial %s: %w", addr, err)
	}
	return &MLClient{conn: conn, c: forecastv1.NewForecasterServiceClient(conn)}, nil
}

func (m *MLClient) Close() error { return m.conn.Close() }

func (m *MLClient) Models(ctx context.Context) ([]ModelInfo, error) {
	resp, err := m.c.ListModels(ctx, &forecastv1.ListModelsRequest{})
	if err != nil {
		return nil, err
	}
	out := make([]ModelInfo, len(resp.GetModels()))
	for i, mi := range resp.GetModels() {
		out[i] = ModelInfo{Name: mi.GetName(), Description: mi.GetDescription(), IsDefault: mi.GetIsDefault()}
	}
	return out, nil
}

func (m *MLClient) Forecast(ctx context.Context, req StochasticRequest) (StochasticForecast, error) {
	pb := &forecastv1.ForecastRequest{
		Model:       req.Model,
		CompanyId:   req.CompanyID,
		Industry:    req.Industry,
		History:     make([]*forecastv1.DailyFlow, len(req.History)),
		HorizonDays: int32(req.Horizon),
		NPaths:      int32(req.NPaths),
		Seed:        req.Seed,
	}
	for i, f := range req.History {
		pb.History[i] = &forecastv1.DailyFlow{
			Date:    f.Date.Format(domain.DateLayout),
			Inflow:  f.Inflow.Float(),
			Outflow: f.Outflow.Float(),
			Missing: f.Missing,
		}
		if len(f.ByCategory) > 0 {
			m := make(map[string]float64, len(f.ByCategory))
			for c, v := range f.ByCategory {
				m[string(c)] = v.Float()
			}
			pb.History[i].ByCategory = m
		}
	}
	resp, err := m.c.Forecast(ctx, pb)
	if err != nil {
		return StochasticForecast{}, err
	}

	out := StochasticForecast{
		ModelUsed:     resp.GetModelUsed(),
		Dates:         make([]time.Time, len(resp.GetDates())),
		Inflow:        make([][]float64, len(resp.GetPaths())),
		Outflow:       make([][]float64, len(resp.GetPaths())),
		LowConfidence: resp.GetLowConfidence(),
	}
	for i, s := range resp.GetDates() {
		if out.Dates[i], err = time.Parse(domain.DateLayout, s); err != nil {
			return StochasticForecast{}, fmt.Errorf("ml: bad date %q: %w", s, err)
		}
	}
	for p, path := range resp.GetPaths() {
		out.Inflow[p], out.Outflow[p] = path.GetInflow(), path.GetOutflow()
	}
	return out, nil
}
