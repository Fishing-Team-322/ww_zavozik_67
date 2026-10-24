// Package dadata reads public registration details by INN or OGRN.
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
	"strconv"
	"strings"
	"time"
)

const DefaultEndpoint = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
const maxResponseBytes = 1 << 20

var ErrInvalidINN = errors.New("invalid INN or OGRN")
var ErrConfig = errors.New("invalid DaData configuration")
var ErrAuth = errors.New("DaData authentication failed")
var ErrRateLimited = errors.New("DaData rate limit exceeded")
var ErrUnavailable = errors.New("DaData unavailable or returned invalid data")
var ErrNotFound = errors.New("company not found in DaData")

type Client struct {
	Token    string
	Endpoint string // Override only for a controlled test server.
	HTTP     *http.Client
	Cache    *Cache
}

type Party struct {
	INN              string  `json:"inn"`
	KPP              string  `json:"kpp,omitempty"`
	OGRN             string  `json:"ogrn"`
	Name             string  `json:"name"`
	Type             string  `json:"type"`
	Status           string  `json:"status"`
	Address          string  `json:"address,omitempty"`
	RegistrationDate *string `json:"registration_date,omitempty"`
	ActualityDate    *string `json:"actuality_date,omitempty"`
	CheckedAt        string  `json:"checked_at"`
	SourceKind       string  `json:"source_kind"`
	SourceURL        string  `json:"source_url"`
	DataMode         string  `json:"data_mode"`
}

// Lookup accepts a checksum-valid 10/12 digit INN or 13/15 digit OGRN.
func (c Client) Lookup(ctx context.Context, identifier string) (Party, error) {
	var empty Party
	if !validIdentifier(identifier) {
		return empty, ErrInvalidINN
	}
	if c.Token == "" {
		return empty, ErrConfig
	}
	if cached, ok := c.Cache.get(identifier); ok {
		return cached, nil
	}
	endpoint := c.Endpoint
	if endpoint == "" {
		endpoint = DefaultEndpoint
	}
	u, err := url.Parse(endpoint)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" ||
		(u.Scheme != "https" && !(u.Scheme == "http" && loopback(u.Hostname()))) {
		return empty, ErrConfig
	}
	if _, ok := ctx.Deadline(); !ok {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, 10*time.Second)
		defer cancel()
	}
	requestBody, _ := json.Marshal(map[string]any{"query": identifier, "count": 1, "branch_type": "MAIN"})
	httpClient := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if c.HTTP != nil {
		httpClient.Transport = c.HTTP.Transport
	}
	for attempt := 0; attempt < 3; attempt++ {
		party, retryAfter, err := c.lookupOnce(ctx, httpClient, endpoint, identifier, requestBody)
		if err == nil {
			party.SourceKind = "dadata"
			party.SourceURL = DefaultEndpoint
			party.DataMode = "live"
			if c.Endpoint != "" {
				party.DataMode = "mock"
			}
			party.CheckedAt = time.Now().UTC().Format(time.RFC3339Nano)
			c.Cache.put(identifier, party)
			return party, nil
		}
		if attempt == 2 || (!errors.Is(err, ErrRateLimited) && !errors.Is(err, ErrUnavailable)) {
			return empty, err
		}
		delay := time.Duration(100*(1<<attempt)) * time.Millisecond
		if retryAfter > delay {
			delay = retryAfter
		}
		if delay > 2*time.Second {
			delay = 2 * time.Second
		}
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return empty, ErrUnavailable
		case <-timer.C:
		}
	}
	return empty, ErrUnavailable
}

func (c Client) lookupOnce(ctx context.Context, client *http.Client, endpoint, identifier string, body []byte) (Party, time.Duration, error) {
	var empty Party
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return empty, 0, ErrConfig
	}
	req.Header.Set("Authorization", "Token "+c.Token)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return empty, 0, ErrUnavailable
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusUnauthorized, http.StatusForbidden:
		return empty, 0, ErrAuth
	case http.StatusTooManyRequests:
		seconds, _ := strconv.Atoi(resp.Header.Get("Retry-After"))
		return empty, time.Duration(seconds) * time.Second, ErrRateLimited
	case http.StatusOK:
		// Continue below.
	default:
		return empty, 0, ErrUnavailable
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
	if err != nil || len(data) > maxResponseBytes {
		return empty, 0, ErrUnavailable
	}
	var result struct {
		Suggestions []struct {
			Data struct {
				INN  string `json:"inn"`
				KPP  string `json:"kpp"`
				OGRN string `json:"ogrn"`
				Type string `json:"type"`
				Name struct {
					Full  string `json:"full_with_opf"`
					Short string `json:"short_with_opf"`
				} `json:"name"`
				State struct {
					Status           string `json:"status"`
					RegistrationDate *int64 `json:"registration_date"`
					ActualityDate    *int64 `json:"actuality_date"`
				} `json:"state"`
				Address struct {
					Value string `json:"value"`
				} `json:"address"`
			} `json:"data"`
		} `json:"suggestions"`
	}
	if json.Unmarshal(data, &result) != nil || result.Suggestions == nil {
		return empty, 0, ErrUnavailable
	}
	if len(result.Suggestions) == 0 {
		return empty, 0, ErrNotFound
	}
	d := result.Suggestions[0].Data
	if ((len(identifier) == 10 || len(identifier) == 12) && d.INN != identifier) ||
		((len(identifier) == 13 || len(identifier) == 15) && d.OGRN != identifier) ||
		!validINN(d.INN) || (d.Type != "LEGAL" && d.Type != "INDIVIDUAL") ||
		(d.Type == "LEGAL" && len(d.INN) != 10) || (d.Type == "INDIVIDUAL" && len(d.INN) != 12) ||
		!validIdentifier(d.OGRN) || d.State.Status == "" {
		return empty, 0, ErrUnavailable
	}
	name := d.Name.Short
	if name == "" {
		name = d.Name.Full
	}
	if strings.TrimSpace(name) == "" {
		return empty, 0, ErrUnavailable
	}
	party := Party{INN: d.INN, OGRN: d.OGRN, Name: strings.TrimSpace(name), Type: d.Type,
		Status: d.State.Status, Address: strings.TrimSpace(d.Address.Value)}
	if d.Type == "LEGAL" {
		party.KPP = d.KPP
	}
	if d.State.RegistrationDate != nil {
		date := time.UnixMilli(*d.State.RegistrationDate).UTC().Format("2006-01-02")
		party.RegistrationDate = &date
	}
	if d.State.ActualityDate != nil {
		date := time.UnixMilli(*d.State.ActualityDate).UTC().Format("2006-01-02")
		party.ActualityDate = &date
	}
	return party, 0, nil
}

func validIdentifier(s string) bool {
	switch len(s) {
	case 10, 12:
		return validINN(s)
	case 13, 15:
		if !allDigits(s) {
			return false
		}
		prefix, _ := strconv.ParseInt(s[:len(s)-1], 10, 64)
		modulus := int64(11)
		if len(s) == 15 {
			modulus = 13
		}
		return (prefix%modulus)%10 == int64(s[len(s)-1]-'0')
	default:
		return false
	}
}

func validINN(s string) bool {
	if (len(s) != 10 && len(s) != 12) || !allDigits(s) {
		return false
	}
	if len(s) == 10 {
		return checksum(s[:9], []int{2, 4, 10, 3, 5, 9, 4, 6, 8}) == int(s[9]-'0')
	}
	return checksum(s[:10], []int{7, 2, 4, 10, 3, 5, 9, 4, 6, 8}) == int(s[10]-'0') &&
		checksum(s[:11], []int{3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8}) == int(s[11]-'0')
}

func checksum(s string, weights []int) int {
	sum := 0
	for i, weight := range weights {
		sum += int(s[i]-'0') * weight
	}
	return sum % 11 % 10
}

func allDigits(s string) bool {
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return s != ""
}

func loopback(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}
