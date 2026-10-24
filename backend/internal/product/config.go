package product

import (
	"encoding/base64"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/config"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

func New(db *store.Postgres, c config.Config, ml forecast.StochasticForecaster) (*Service, error) {
	if c.IntegrationSandbox {
		for _, origin := range []string{c.PublicURL, c.FrontendURL} {
			u, e := url.Parse(origin)
			if e != nil || u.Hostname() != "localhost" && (net.ParseIP(u.Hostname()) == nil || !net.ParseIP(u.Hostname()).IsLoopback()) {
				return nil, fmt.Errorf("integration sandbox requires loopback origins")
			}
		}
	}
	if c.FNSHubURL != "" {
		u, e := url.Parse(c.FNSHubURL)
		if e != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" && u.Path != "/" || u.Scheme != "https" && u.Scheme != "http" || c.FNSHubToken == "" || c.FNSHubCompany == "" {
			return nil, fmt.Errorf("invalid operator FNS Hub configuration")
		}
	}

	var key []byte
	if c.DataEncryptionKey != "" {
		var e error
		key, e = base64.StdEncoding.DecodeString(c.DataEncryptionKey)
		if e != nil || len(key) != 32 {
			return nil, fmt.Errorf("DATA_ENCRYPTION_KEY must be base64 containing 32 bytes")
		}
	}
	if c.TrainingURL != "" {
		u, e := url.Parse(c.TrainingURL)
		if e != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
			return nil, fmt.Errorf("invalid TRAINING_URL")
		}
		ip := net.ParseIP(u.Hostname())
		local := u.Hostname() == "localhost" || ip != nil && ip.IsLoopback()
		if u.Scheme != "https" && !(u.Scheme == "http" && local) {
			return nil, fmt.Errorf("TRAINING_URL requires HTTPS or loopback")
		}
	}
	hosts := []string{}
	for _, h := range strings.Split(c.SourceAllowedHosts, ",") {
		if h = strings.TrimSpace(h); h != "" {
			hosts = append(hosts, h)
		}
	}
	service := &Service{IntegrationSandbox: c.IntegrationSandbox, FNSHubURL: c.FNSHubURL, FNSHubToken: c.FNSHubToken, FNSHubCompany: c.FNSHubCompany, DB: db, ML: forecast.NewCachedForecaster(ml, time.Minute, 16), Fallback: forecast.SeasonalNaive{}, EncryptionKey: key, AllowedSourceHosts: hosts, DaDataToken: c.DaDataToken, ReportsDir: c.ModelReportsDir, TrainingURL: c.TrainingURL, TrainingToken: c.TrainingToken}
	if c.IntegrationSandbox {
		service.HTTP = &http.Client{Transport: sandboxTransport{}}
		service.DaDataToken = "sandbox-key"
	}
	return service, nil
}
