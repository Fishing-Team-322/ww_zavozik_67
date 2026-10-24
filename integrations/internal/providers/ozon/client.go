package ozon

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

const Endpoint = "https://api-seller.ozon.ru/v3/finance/transaction/list"

// Entry is an accrual or charge inside Ozon, never an executed bank operation.
type Entry struct {
	ExternalID            string `json:"external_id"`
	OperationType         string `json:"operation_type"`
	Category              string `json:"category"`
	OperationDate         string `json:"operation_date"`
	AmountKopecks         int64  `json:"amount_kopecks"`
	AccrualsKopecks       int64  `json:"accruals_kopecks"`
	SaleCommissionKopecks int64  `json:"sale_commission_kopecks"`
	DeliveryChargeKopecks int64  `json:"delivery_charge_kopecks"`
	Currency              string `json:"currency"`
	Source                string `json:"source"`
	DataMode              string `json:"data_mode"`
	ForecastEligible      bool   `json:"forecast_eligible"`
}

type rawOperation struct {
	ID             json.Number `json:"operation_id"`
	Type           string      `json:"operation_type"`
	Date           string      `json:"operation_date"`
	Amount         json.Number `json:"amount"`
	Accruals       json.Number `json:"accruals_for_sale"`
	SaleCommission json.Number `json:"sale_commission"`
	DeliveryCharge json.Number `json:"delivery_charge"`
}

type Client struct {
	HTTP        *http.Client
	ClientID    string
	APIKey      string
	EndpointURL string // test override
}

func (c Client) Fetch(ctx context.Context, from, to time.Time) ([]Entry, error) {
	if c.ClientID == "" || c.APIKey == "" {
		return nil, errors.New("Ozon Seller credentials are missing")
	}
	if to.Before(from) || to.Sub(from) > 31*24*time.Hour {
		return nil, errors.New("Ozon interval must be at most one month")
	}
	if c.HTTP == nil {
		c.HTTP = &http.Client{Timeout: 30 * time.Second}
	}
	url := c.EndpointURL
	mode := "mock"
	if url == "" {
		url = Endpoint
		mode = "live"
	}
	var out []Entry
	seen := map[string]bool{}
	for page := 1; page <= 1000; page++ {
		body, _ := json.Marshal(map[string]any{
			"filter": map[string]any{"date": map[string]string{"from": from.UTC().Format(time.RFC3339), "to": to.UTC().Format(time.RFC3339)}, "operation_type": []string{}, "posting_number": "", "transaction_type": "all"},
			"page":   page, "page_size": 1000,
		})
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
		if err != nil {
			return nil, errors.New("invalid Ozon endpoint")
		}
		req.Header.Set("Client-Id", c.ClientID)
		req.Header.Set("Api-Key", c.APIKey)
		req.Header.Set("Content-Type", "application/json")
		resp, err := c.HTTP.Do(req)
		if err != nil {
			return nil, fmt.Errorf("Ozon request failed: %w", err)
		}
		if resp.StatusCode != http.StatusOK {
			resp.Body.Close()
			return nil, fmt.Errorf("Ozon Seller HTTP %d", resp.StatusCode)
		}
		var payload struct {
			Result struct {
				Operations []rawOperation `json:"operations"`
				PageCount  int            `json:"page_count"`
			} `json:"result"`
		}
		dec := json.NewDecoder(io.LimitReader(resp.Body, 16<<20))
		dec.UseNumber()
		err = dec.Decode(&payload)
		resp.Body.Close()
		if err != nil || payload.Result.PageCount < 0 || payload.Result.PageCount > 1000 {
			return nil, errors.New("invalid Ozon response")
		}
		for _, op := range payload.Result.Operations {
			if op.ID == "" || op.Type == "" || op.Date == "" || op.Amount == "" {
				return nil, errors.New("incomplete Ozon operation")
			}
			if _, err := time.Parse(time.RFC3339Nano, op.Date); err != nil {
				return nil, errors.New("invalid Ozon operation date")
			}
			id := op.ID.String()
			if _, err := strconv.ParseInt(id, 10, 64); err != nil {
				return nil, errors.New("invalid Ozon operation id")
			}
			amount, err := parse(op.Amount)
			if err != nil {
				return nil, errors.New("invalid Ozon operation amount")
			}
			accrual, err := parseOptional(op.Accruals)
			if err != nil {
				return nil, errors.New("invalid Ozon accrual")
			}
			commission, err := parseOptional(op.SaleCommission)
			if err != nil {
				return nil, errors.New("invalid Ozon commission")
			}
			delivery, err := parseOptional(op.DeliveryCharge)
			if err != nil {
				return nil, errors.New("invalid Ozon delivery charge")
			}
			if seen[id] {
				continue
			}
			seen[id] = true
			category := "other"
			lower := strings.ToLower(op.Type)
			switch {
			case strings.Contains(lower, "return"):
				category = "return"
			case strings.Contains(lower, "delivery"):
				category = "logistics"
			case strings.Contains(lower, "sale") || strings.Contains(lower, "delivered"):
				category = "sale"
			case strings.Contains(lower, "service") || strings.Contains(lower, "commission"):
				category = "fee"
			}
			out = append(out, Entry{ExternalID: id, OperationType: op.Type, Category: category, OperationDate: op.Date, AmountKopecks: amount, AccrualsKopecks: accrual, SaleCommissionKopecks: commission, DeliveryChargeKopecks: delivery, Currency: "RUB", Source: "ozon_finance", DataMode: mode, ForecastEligible: false})
		}
		if payload.Result.PageCount == 0 || page >= payload.Result.PageCount {
			return out, nil
		}
		if len(payload.Result.Operations) == 0 {
			return nil, errors.New("empty Ozon page before page_count")
		}
	}
	return nil, errors.New("Ozon page limit exceeded")
}

func parse(n json.Number) (int64, error) {
	s := n.String()
	if strings.HasPrefix(s, "-") {
		v, e := money.Parse(s[1:])
		return -v, e
	}
	return money.Parse(s)
}
func parseOptional(n json.Number) (int64, error) {
	if n == "" {
		return 0, nil
	}
	return parse(n)
}
