// Package onecodata reads configured 1C OData collections without modifying 1C.
package onecodata

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/money"
)

const maxPageBytes = 2 << 20
const maxPages = 20
const maxRecords = 4000

var ErrConfig = errors.New("invalid OData configuration")
var ErrUpstream = errors.New("OData source unavailable or returned invalid data")
var ErrAuth = errors.New("OData authentication failed")
var ErrLimit = errors.New("OData response exceeds limit")

// FieldMap names the JSON fields actually published by a 1C configuration.
// Dot paths may refer to expanded nested objects.
type FieldMap struct {
	ExternalID       string `json:"external_id"`
	Number           string `json:"number"`
	DocumentDate     string `json:"document_date"`
	ExecutionDate    string `json:"execution_date"`
	Amount           string `json:"amount"`
	Posted           string `json:"posted"`
	Unconfirmed      string `json:"unconfirmed,omitempty"`
	AccountKey       string `json:"account_key"`
	CounterpartyINN  string `json:"counterparty_inn"`
	CounterpartyName string `json:"counterparty_name"`
	CounterpartyKey  string `json:"counterparty_key,omitempty"`
	Purpose          string `json:"purpose"`
}

// ReferenceCatalog resolves polymorphic 1C references to counterparty details.
type ReferenceCatalog struct {
	EntitySet string `json:"entity_set"`
	Key       string `json:"key"`
	INN       string `json:"inn"`
	Name      string `json:"name"`
}

type Collection struct {
	EntitySet string   `json:"entity_set"`
	Direction string   `json:"direction"`
	Expand    []string `json:"expand,omitempty"`
	Fields    FieldMap `json:"fields"`
}

type Config struct {
	BaseURL        string            `json:"base_url"`
	CompanyID      string            `json:"company_id"`
	CompanyINN     string            `json:"company_inn"`
	CompanyAccount string            `json:"company_account"`
	AccountMap     map[string]string `json:"account_map"`
	Counterparties *ReferenceCatalog `json:"counterparties,omitempty"`
	Collections    []Collection      `json:"collections"`
}

// LoadConfig reads a small operator-owned file. Credentials must be supplied separately.
func LoadConfig(path string) (Config, error) {
	var cfg Config
	if path == "" {
		return cfg, ErrConfig
	}
	f, err := os.Open(path)
	if err != nil {
		return cfg, ErrConfig
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, (64<<10)+1))
	if err != nil || len(data) > 64<<10 {
		return cfg, ErrConfig
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&cfg) != nil || decoder.Decode(new(any)) != io.EOF || cfg.Validate() != nil {
		return Config{}, ErrConfig
	}
	return cfg, nil
}

func (c Config) Identity() contracts.Identity {
	return contracts.Identity{CompanyID: c.CompanyID, CompanyINN: c.CompanyINN, CompanyAccount: c.CompanyAccount}
}

func (c Config) Validate() error {
	if c.Identity().Validate() != nil {
		return ErrConfig
	}
	u, err := url.Parse(c.BaseURL)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Scheme != "https" && u.Scheme != "http") || !strings.HasSuffix(u.Path, "/") {
		return ErrConfig
	}
	if u.Scheme == "http" && !isLoopback(u.Hostname()) {
		return ErrConfig
	}
	if len(c.AccountMap) == 0 || len(c.Collections) == 0 || len(c.Collections) > 8 {
		return ErrConfig
	}
	if c.Counterparties != nil && (!validEntity(c.Counterparties.EntitySet) || !validField(c.Counterparties.Key) || !validField(c.Counterparties.INN) || !validField(c.Counterparties.Name)) {
		return ErrConfig
	}
	for key, account := range c.AccountMap {
		if strings.TrimSpace(key) == "" || len(key) > 128 || len(account) != 20 || !digits(account) {
			return ErrConfig
		}
	}
	seen := map[string]bool{}
	for _, col := range c.Collections {
		if !validEntity(col.EntitySet) || seen[col.EntitySet] || (col.Direction != "in" && col.Direction != "out") {
			return ErrConfig
		}
		seen[col.EntitySet] = true
		f := col.Fields
		for _, name := range []string{f.ExternalID, f.Number, f.DocumentDate, f.ExecutionDate, f.Amount, f.Posted, f.AccountKey} {
			if !validField(name) {
				return ErrConfig
			}
		}
		for _, name := range []string{f.CounterpartyINN, f.CounterpartyName, f.CounterpartyKey, f.Purpose} {
			if name != "" && !validField(name) {
				return ErrConfig
			}
		}
		if f.Unconfirmed != "" && !validField(f.Unconfirmed) {
			return ErrConfig
		}
		if len(col.Expand) > 4 {
			return ErrConfig
		}
		for _, name := range col.Expand {
			if !validEntity(name) {
				return ErrConfig
			}
		}
	}
	return nil
}

func isLoopback(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func digits(s string) bool {
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return s != ""
}

func validEntity(s string) bool {
	if s == "" || len(s) > 128 {
		return false
	}
	for _, r := range s {
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) && r != '_' {
			return false
		}
	}
	return true
}

func validField(s string) bool {
	if s == "" || len(s) > 128 || strings.HasPrefix(s, ".") || strings.HasSuffix(s, ".") || strings.Contains(s, "..") {
		return false
	}
	for _, r := range s {
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) && r != '_' && r != '.' {
			return false
		}
	}
	return true
}

type Client struct {
	HTTP     *http.Client
	Username string
	Password string
}

func (Client) Kind() string { return contracts.SourceOneCOData }

// Fetch reads only configured collections. Credentials and raw upstream bodies never enter errors.
func (c Client) Fetch(ctx context.Context, cfg Config) (contracts.ImportBatch, error) {
	batch := contracts.NewBatchFor(cfg.CompanyID, contracts.SourceOneCOData, "pull")
	if err := cfg.Validate(); err != nil {
		return batch, err
	}
	if c.Username == "" && c.Password != "" {
		return batch, ErrConfig
	}
	if _, ok := ctx.Deadline(); !ok {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, 30*time.Second)
		defer cancel()
	}
	httpClient := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if c.HTTP != nil {
		httpClient.Transport = c.HTTP.Transport
	}
	counterparties := map[string]struct{ inn, name string }{}
	if cfg.Counterparties != nil {
		var err error
		counterparties, err = c.readCounterparties(ctx, httpClient, cfg)
		if err != nil {
			return batch, err
		}
	}
	seen := map[string]bool{}
	for _, col := range cfg.Collections {
		base, _ := url.Parse(strings.TrimRight(cfg.BaseURL, "/") + "/" + url.PathEscape(col.EntitySet))
		query := base.Query()
		query.Set("$format", "json")
		query.Set("$top", "200")
		if len(col.Expand) > 0 {
			query.Set("$expand", strings.Join(col.Expand, ","))
		}
		base.RawQuery = query.Encode()
		next := base.String()
		visited := map[string]bool{}
		for page := 0; next != ""; page++ {
			if page >= maxPages || visited[next] {
				return batch, ErrLimit
			}
			visited[next] = true
			rows, link, err := c.readPage(ctx, httpClient, next)
			if err != nil {
				return batch, err
			}
			for _, row := range rows {
				if batch.Stats.Parsed >= maxRecords {
					return batch, ErrLimit
				}
				batch.Stats.Parsed++
				op, code := mapRecord(row, col, cfg.AccountMap)
				if code != "" {
					batch.Stats.Rejected++
					batch.Issues = append(batch.Issues, contracts.Issue{Code: code, Section: batch.Stats.Parsed, Message: "OData record was skipped"})
					continue
				}
				if ref := getString(row, col.Fields.CounterpartyKey); ref != "" {
					if cp, ok := counterparties[ref]; ok {
						op.CounterpartyINN = cp.inn
						op.CounterpartyName = cp.name
					}
				}
				if seen[op.DedupKey] {
					batch.Stats.Duplicates++
					continue
				}
				seen[op.DedupKey] = true
				batch.Operations = append(batch.Operations, op)
				batch.Stats.Accepted++
			}
			if link == "" {
				next = ""
				continue
			}
			u, err := base.Parse(link)
			if err != nil || u.Scheme != base.Scheme || u.Host != base.Host || u.Path != base.Path || u.User != nil || u.Fragment != "" {
				return batch, ErrUpstream
			}
			next = u.String()
		}
	}
	return batch, nil
}

func (c Client) readCounterparties(ctx context.Context, client *http.Client, cfg Config) (map[string]struct{ inn, name string }, error) {
	result := map[string]struct{ inn, name string }{}
	spec := cfg.Counterparties
	base, _ := url.Parse(strings.TrimRight(cfg.BaseURL, "/") + "/" + url.PathEscape(spec.EntitySet))
	query := base.Query()
	query.Set("$format", "json")
	query.Set("$top", "200")
	query.Set("$select", strings.Join([]string{spec.Key, spec.INN, spec.Name}, ","))
	base.RawQuery = query.Encode()
	next := base.String()
	visited := map[string]bool{}
	for page := 0; next != ""; page++ {
		if page >= maxPages || visited[next] {
			return nil, ErrLimit
		}
		visited[next] = true
		rows, link, err := c.readPage(ctx, client, next)
		if err != nil {
			return nil, err
		}
		for _, row := range rows {
			if len(result) >= maxRecords {
				return nil, ErrLimit
			}
			key := getString(row, spec.Key)
			if key != "" {
				result[key] = struct{ inn, name string }{getString(row, spec.INN), normText(getString(row, spec.Name))}
			}
		}
		if link == "" {
			break
		}
		u, err := base.Parse(link)
		if err != nil || u.Scheme != base.Scheme || u.Host != base.Host || u.Path != base.Path || u.User != nil || u.Fragment != "" {
			return nil, ErrUpstream
		}
		next = u.String()
	}
	return result, nil
}

func (c Client) readPage(ctx context.Context, client *http.Client, pageURL string) ([]map[string]any, string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, pageURL, nil)
	if err != nil {
		return nil, "", ErrConfig
	}
	req.Header.Set("Accept", "application/json")
	if c.Username != "" {
		req.SetBasicAuth(c.Username, c.Password)
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, "", ErrUpstream
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
		return nil, "", ErrAuth
	}
	if resp.StatusCode != http.StatusOK {
		return nil, "", ErrUpstream
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxPageBytes+1))
	if err != nil {
		return nil, "", ErrUpstream
	}
	if len(data) > maxPageBytes {
		return nil, "", ErrLimit
	}
	var envelope struct {
		Value   json.RawMessage `json:"value"`
		Next    string          `json:"@odata.nextLink"`
		NextV3  string          `json:"odata.nextLink"`
		NextOld string          `json:"__next"`
		D       struct {
			Results json.RawMessage `json:"results"`
			Next    string          `json:"__next"`
		} `json:"d"`
	}
	if json.Unmarshal(data, &envelope) != nil {
		return nil, "", ErrUpstream
	}
	raw := envelope.Value
	if len(raw) == 0 {
		raw = envelope.D.Results
	}
	if len(raw) == 0 {
		return nil, "", ErrUpstream
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var rows []map[string]any
	if decoder.Decode(&rows) != nil || rows == nil {
		return nil, "", ErrUpstream
	}
	link := envelope.Next
	if link == "" {
		link = envelope.NextV3
	}
	if link == "" {
		link = envelope.NextOld
	}
	if link == "" {
		link = envelope.D.Next
	}
	return rows, link, nil
}

func mapRecord(row map[string]any, col Collection, accounts map[string]string) (contracts.Operation, string) {
	var op contracts.Operation
	f := col.Fields
	if getString(row, f.Posted) != "true" {
		return op, "not_posted"
	}
	if f.Unconfirmed != "" && getString(row, f.Unconfirmed) == "true" {
		return op, "unconfirmed_by_bank"
	}
	key := getString(row, f.AccountKey)
	account, ok := accounts[key]
	if !ok {
		return op, "unknown_account"
	}
	id := getString(row, f.ExternalID)
	if id == "" {
		return op, "missing_external_id"
	}
	if getString(row, f.Number) == "" {
		return op, "missing_document_number"
	}
	if _, err := parseDate(getString(row, f.DocumentDate)); err != nil {
		return op, "invalid_document_date"
	}
	date, err := parseDate(getString(row, f.ExecutionDate))
	if err != nil {
		return op, "invalid_execution_date"
	}
	amount, err := money.Parse(getString(row, f.Amount))
	if err != nil {
		return op, "invalid_amount"
	}
	op.ExternalID = id
	op.Date = date
	op.AmountKopecks = amount
	op.Direction = col.Direction
	op.CounterpartyINN = getString(row, f.CounterpartyINN)
	op.CounterpartyName = normText(getString(row, f.CounterpartyName))
	op.Purpose = normText(getString(row, f.Purpose))
	op.SourceKind = contracts.SourceOneCOData
	op.Account = account
	op.Executed = true
	hash := sha256.Sum256([]byte(strings.Join([]string{contracts.SourceOneCOData, col.EntitySet, id, account}, "\x00")))
	op.DedupKey = hex.EncodeToString(hash[:])
	return op, ""
}

func getString(row map[string]any, path string) string {
	if path == "" {
		return ""
	}
	var value any = row
	for _, part := range strings.Split(path, ".") {
		obj, ok := value.(map[string]any)
		if !ok {
			return ""
		}
		value = obj[part]
	}
	switch v := value.(type) {
	case string:
		return strings.TrimSpace(v)
	case json.Number:
		return v.String()
	case bool:
		return strconv.FormatBool(v)
	default:
		return ""
	}
}

func parseDate(s string) (string, error) {
	s = strings.TrimSpace(s)
	if strings.HasPrefix(s, "/Date(") && strings.HasSuffix(s, ")/") {
		millis, err := strconv.ParseInt(strings.TrimSuffix(strings.TrimPrefix(s, "/Date("), ")/"), 10, 64)
		if err != nil {
			return "", ErrUpstream
		}
		return time.UnixMilli(millis).UTC().Format("2006-01-02"), nil
	}
	if day, err := time.Parse("2006-01-02", s); err == nil {
		return day.Format("2006-01-02"), nil
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05", "2006-01-02T15:04:05.999999999"} {
		if stamp, err := time.Parse(layout, s); err == nil {
			return stamp.Format("2006-01-02"), nil
		}
	}
	return "", ErrUpstream
}

func normText(s string) string { return strings.Join(strings.Fields(s), " ") }
