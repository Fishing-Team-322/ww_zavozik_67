// Package dadata reads company details by INN from the DaData API.
package dadata

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const DefaultEndpoint = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
const maxResponseBytes = 1 << 20

var ErrInvalidINN = errors.New("invalid INN")
var ErrConfig = errors.New("invalid DaData configuration")
var ErrAuth = errors.New("DaData authentication or quota failed")
var ErrUnavailable = errors.New("DaData unavailable or returned invalid data")
var ErrNotFound = errors.New("company not found in DaData")

type Client struct {
	Token    string
	Endpoint string // Only tests should override the official endpoint.
	HTTP     *http.Client
}

type Party struct {
	INN        string `json:"inn"`
	KPP        string `json:"kpp"`
	OGRN       string `json:"ogrn"`
	Name       string `json:"name"`
	Status     string `json:"status"`
	Address    string `json:"address"`
	SourceKind string `json:"source_kind"`
}

func (c Client) Lookup(ctx context.Context, inn string) (Party, error) {
	var empty Party
	if !validINN(inn) {
		return empty, ErrInvalidINN
	}
	if c.Token == "" {
		return empty, ErrConfig
	}
	endpoint := c.Endpoint
	if endpoint == "" {
		endpoint = DefaultEndpoint
	}
	u, err := url.Parse(endpoint)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Scheme != "https" && !(u.Scheme == "http" && loopback(u.Hostname()))) {
		return empty, ErrConfig
	}
	body, _ := json.Marshal(map[string]any{"query": inn, "count": 1, "branch_type": "MAIN"})
	if _, ok := ctx.Deadline(); !ok {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, 10*time.Second)
		defer cancel()
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return empty, ErrConfig
	}
	req.Header.Set("Authorization", "Token "+c.Token)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	httpClient := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if c.HTTP != nil {
		httpClient.Transport = c.HTTP.Transport
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return empty, ErrUnavailable
	}
	defer resp.Body.Close()
	if resp.StatusCode == 401 || resp.StatusCode == 403 || resp.StatusCode == 429 {
		return empty, ErrAuth
	}
	if resp.StatusCode != 200 {
		return empty, ErrUnavailable
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
	if err != nil || len(data) > maxResponseBytes {
		return empty, ErrUnavailable
	}
	var result struct {
		Suggestions []struct {
			Data struct {
				INN  string `json:"inn"`
				KPP  string `json:"kpp"`
				OGRN string `json:"ogrn"`
				Name struct {
					Full  string `json:"full_with_opf"`
					Short string `json:"short_with_opf"`
				} `json:"name"`
				State struct {
					Status string `json:"status"`
				} `json:"state"`
				Address struct {
					Value string `json:"value"`
				} `json:"address"`
			} `json:"data"`
		} `json:"suggestions"`
	}
	if json.Unmarshal(data, &result) != nil || result.Suggestions == nil {
		return empty, ErrUnavailable
	}
	if len(result.Suggestions) == 0 {
		return empty, ErrNotFound
	}
	d := result.Suggestions[0].Data
	if d.INN != inn {
		return empty, ErrUnavailable
	}
	name := d.Name.Short
	if name == "" {
		name = d.Name.Full
	}
	return Party{INN: d.INN, KPP: d.KPP, OGRN: d.OGRN, Name: strings.TrimSpace(name), Status: d.State.Status, Address: strings.TrimSpace(d.Address.Value), SourceKind: "dadata"}, nil
}

func validINN(s string) bool {
	if len(s) != 10 && len(s) != 12 {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func loopback(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}
