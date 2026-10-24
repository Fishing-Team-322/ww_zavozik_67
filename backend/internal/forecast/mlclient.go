package forecast

import (
	"context"
	"fmt"
	"math"
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

const BusinessFlowScope = "business_without_internal_transfers"

// maxRecvBytes — потолок gRPC-сообщения, как в ml/zavozik_ml/serving/server.py:
// 5000 путей × 366 дней не влезают в дефолтные 4 МиБ gRPC.
const maxRecvBytes = 64 << 20

// DialML не ходит в сеть: соединение ленивое, сервис может подняться позже.
// Внутри docker-сети без TLS; наружу ML-сервис не публикуется.
func DialML(addr string) (*MLClient, error) {
	conn, err := grpc.NewClient(addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(maxRecvBytes), grpc.MaxCallSendMsgSize(maxRecvBytes)),
	)
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
	if err := validateRequest(req); err != nil {
		return StochasticForecast{}, err
	}
	pb := &forecastv1.ForecastRequest{
		Model:       req.Model,
		CompanyId:   req.CompanyID,
		Industry:    req.Industry,
		History:     make([]*forecastv1.DailyFlow, len(req.History)),
		HorizonDays: int32(req.Horizon),
		NPaths:      int32(req.NPaths),
		Seed:        req.Seed,
		FlowScope:   req.FlowScope,
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
	for _, tx := range req.Transactions {
		pb.Transactions = append(pb.Transactions, &forecastv1.HistoryTransaction{Id: tx.ID, Date: tx.Date.Format(domain.DateLayout), Amount: tx.Amount.Float(), Direction: string(tx.Direction), Category: string(tx.Category), CounterpartyId: tx.CounterpartyID, Purpose: string(tx.Purpose)})
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
		ModelVersion:  resp.GetModelVersion(),
		FlowScope:     resp.GetFlowScope(),
		Warnings:      resp.GetWarnings(),
		FallbackUsed:  resp.GetFallbackUsed(),
	}
	if len(out.Dates) != req.Horizon || len(out.Inflow) != req.NPaths {
		return StochasticForecast{}, fmt.Errorf("ml: invalid response dimensions")
	}
	if out.FlowScope != "" && out.FlowScope != BusinessFlowScope {
		return StochasticForecast{}, fmt.Errorf("ml: unsupported response flow scope %q", out.FlowScope)
	}
	for i, s := range resp.GetDates() {
		if out.Dates[i], err = time.Parse(domain.DateLayout, s); err != nil {
			return StochasticForecast{}, fmt.Errorf("ml: bad date %q: %w", s, err)
		}
		if len(req.History) > 0 && !out.Dates[i].Equal(domain.Day(req.History[len(req.History)-1].Date).AddDate(0, 0, i+1)) {
			return StochasticForecast{}, fmt.Errorf("ml: unexpected forecast date")
		}
	}
	for p, path := range resp.GetPaths() {
		out.Inflow[p], out.Outflow[p] = path.GetInflow(), path.GetOutflow()
		if len(out.Inflow[p]) != req.Horizon || len(out.Outflow[p]) != req.Horizon {
			return StochasticForecast{}, fmt.Errorf("ml: invalid path length")
		}
		for i, v := range out.Inflow[p] {
			w := out.Outflow[p][i]
			if math.IsNaN(v) || math.IsInf(v, 0) || math.IsNaN(w) || math.IsInf(w, 0) || v < 0 || w < 0 {
				return StochasticForecast{}, fmt.Errorf("ml: invalid path value")
			}
		}
	}
	return out, nil
}
