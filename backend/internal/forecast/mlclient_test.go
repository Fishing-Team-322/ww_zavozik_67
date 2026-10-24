package forecast

import (
	"context"
	forecastv1 "github.com/Fishing-Team-322/ww_zavozik_67/backend/gen/forecast/v1"
	"google.golang.org/grpc"
	"math"
	"testing"
)

type responseClient struct {
	forecastv1.ForecasterServiceClient
	response *forecastv1.ForecastResponse
}

func (f responseClient) Forecast(context.Context, *forecastv1.ForecastRequest, ...grpc.CallOption) (*forecastv1.ForecastResponse, error) {
	return f.response, nil
}

func TestMLClientRejectsMalformedPaths(t *testing.T) {
	cases := map[string]func(*forecastv1.ForecastResponse){
		"path count":  func(r *forecastv1.ForecastResponse) { r.Paths = nil },
		"path length": func(r *forecastv1.ForecastResponse) { r.Paths[0].Outflow = nil },
		"date shift":  func(r *forecastv1.ForecastResponse) { r.Dates[0] = "2025-01-03" },
		"nan":         func(r *forecastv1.ForecastResponse) { r.Paths[0].Inflow[0] = math.NaN() },
		"infinity":    func(r *forecastv1.ForecastResponse) { r.Paths[0].Inflow[0] = math.Inf(1) },
		"negative":    func(r *forecastv1.ForecastResponse) { r.Paths[0].Outflow[0] = -1 },
		"scope":       func(r *forecastv1.ForecastResponse) { r.FlowScope = "residual_only" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			r := &forecastv1.ForecastResponse{Dates: []string{"2025-01-02"}, Paths: []*forecastv1.Path{{Inflow: []float64{2}, Outflow: []float64{1}}}}
			mutate(r)
			client := MLClient{c: responseClient{response: r}}
			if _, err := client.Forecast(context.Background(), StochasticRequest{History: history(1), Horizon: 1, NPaths: 1}); err == nil {
				t.Fatal("accepted malformed response")
			}
		})
	}
}
