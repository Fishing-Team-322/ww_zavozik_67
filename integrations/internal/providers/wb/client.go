package wb

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/money"
)

const Endpoint = "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed"

// Line is a marketplace accounting row, not an executed bank operation.
type Line struct {
	ReportID      json.Number `json:"reportId"`
	RRDID         json.Number `json:"rrdId"`
	Currency      string      `json:"currency"`
	DocumentType  string      `json:"docTypeName"`
	OperationType string      `json:"sellerOperName"`
	ForPay        string      `json:"forPay"`
	AcquiringFee  string      `json:"acquiringFee"`
	DeliveryRub   string      `json:"deliveryRub"`
}

type Entry struct {
	ExternalID       string `json:"external_id"`
	Category         string `json:"category"`
	AmountKopecks    int64  `json:"amount_kopecks"`
	AcquiringKopecks int64  `json:"acquiring_kopecks"`
	DeliveryKopecks  int64  `json:"delivery_kopecks"`
	Currency         string `json:"currency"`
	Source           string `json:"source"`
	DataMode         string `json:"data_mode"`
	ForecastEligible bool   `json:"forecast_eligible"`
}

type Client struct {
	HTTP        *http.Client
	Token       string
	EndpointURL string // test override; production uses Endpoint
	MinInterval time.Duration
}

func (c Client) Fetch(ctx context.Context, from, to string) ([]Entry, error) {
	start, err := time.Parse("2006-01-02", from)
	if err != nil {
		return nil, errors.New("invalid start date")
	}
	end, err := time.Parse("2006-01-02", to)
	if err != nil || end.Before(start) || end.Sub(start) > 31*24*time.Hour {
		return nil, errors.New("invalid report period")
	}
	if c.Token == "" {
		return nil, errors.New("WB Finance token is missing")
	}
	url := c.EndpointURL
	if url == "" {
		url = Endpoint
	}
	if c.HTTP == nil {
		c.HTTP = &http.Client{Timeout: 30 * time.Second}
	}
	interval := c.MinInterval
	if interval == 0 && c.EndpointURL == "" {
		interval = time.Minute
	}
	mode := "live"
	if c.EndpointURL != "" {
		mode = "mock"
	}
	var out []Entry
	seen := map[string]bool{}
	var rrdID int64
	for page := 0; page < 100; page++ {
		if page > 0 && interval > 0 {
			timer := time.NewTimer(interval)
			select {
			case <-ctx.Done():
				timer.Stop()
				return nil, ctx.Err()
			case <-timer.C:
			}
		}
		body, _ := json.Marshal(map[string]any{"dateFrom": from, "dateTo": to, "period": "weekly", "limit": 100000, "rrdId": rrdID})
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
		if err != nil {
			return nil, errors.New("invalid WB endpoint")
		}
		req.Header.Set("Authorization", c.Token)
		req.Header.Set("Content-Type", "application/json")
		resp, err := c.HTTP.Do(req)
		if err != nil {
			return nil, fmt.Errorf("WB request failed: %w", err)
		}
		if resp.StatusCode == http.StatusNoContent {
			resp.Body.Close()
			return out, nil
		}
		if resp.StatusCode != http.StatusOK {
			resp.Body.Close()
			return nil, fmt.Errorf("WB Finance HTTP %d", resp.StatusCode)
		}
		dec := json.NewDecoder(io.LimitReader(resp.Body, 32<<20))
		dec.UseNumber()
		var rows []Line
		err = dec.Decode(&rows)
		resp.Body.Close()
		if err != nil {
			return nil, errors.New("invalid WB response")
		}
		if len(rows) == 0 {
			return out, nil
		}
		var next int64
		for _, row := range rows {
			id, err := row.RRDID.Int64()
			if err != nil || id <= rrdID || row.ReportID == "" || row.Currency != "RUB" {
				return nil, errors.New("invalid WB report row identity or currency")
			}
			if id > next {
				next = id
			}
			key := row.ReportID.String() + ":" + strconv.FormatInt(id, 10)
			if seen[key] {
				continue
			}
			seen[key] = true
			amount, err := signed(row.ForPay)
			if err != nil {
				return nil, errors.New("invalid WB amount")
			}
			acquiring, err := optional(row.AcquiringFee)
			if err != nil {
				return nil, errors.New("invalid WB acquiring fee")
			}
			delivery, err := optional(row.DeliveryRub)
			if err != nil {
				return nil, errors.New("invalid WB delivery amount")
			}
			category := "other"
			switch {
			case strings.Contains(strings.ToLower(row.DocumentType), "возврат"):
				category = "return"
			case strings.Contains(strings.ToLower(row.DocumentType), "продажа"):
				category = "sale"
			case strings.Contains(strings.ToLower(row.OperationType), "логист"):
				category = "logistics"
			}
			out = append(out, Entry{ExternalID: key, Category: category, AmountKopecks: amount, AcquiringKopecks: acquiring, DeliveryKopecks: delivery, Currency: "RUB", Source: "wildberries_finance", DataMode: mode, ForecastEligible: false})
		}
		if next <= rrdID {
			return nil, errors.New("WB pagination did not advance")
		}
		rrdID = next
	}
	return nil, errors.New("WB page limit exceeded")
}

func signed(s string) (int64, error) {
	if strings.HasPrefix(s, "-") {
		n, err := money.Parse(strings.TrimPrefix(s, "-"))
		return -n, err
	}
	return money.Parse(s)
}

func optional(s string) (int64, error) {
	if s == "" {
		return 0, nil
	}
	return signed(s)
}
