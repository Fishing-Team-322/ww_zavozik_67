// Package config — настройки из переменных окружения.
package config

import (
	"fmt"
	"net"
	"net/mail"
	"net/url"
	"os"
	"strings"
	"time"
)

type Config struct {
	IntegrationSandbox                                                                                               bool
	FNSHubURL, FNSHubToken, FNSHubCompany                                                                            string
	TrustedProxyCIDRs                                                                                                []string
	HTTPAddr                                                                                                         string        // HTTP_ADDR
	DatabaseURL                                                                                                      string        // DATABASE_URL
	MLAddr                                                                                                           string        // ML_ADDR — gRPC Python-сервиса; пусто — только фолбэк
	MLTimeout                                                                                                        time.Duration // ML_TIMEOUT
	JWTSecret                                                                                                        string        // JWT_SECRET
	LogLevel                                                                                                         string        // LOG_LEVEL: debug | info | warn | error
	PublicURL, FrontendURL                                                                                           string
	CookieSecure                                                                                                     bool
	GoogleClientID, GoogleClientSecret                                                                               string
	YandexClientID, YandexClientSecret                                                                               string
	SMTPAddr, SMTPUser, SMTPPassword, SMTPFrom                                                                       string
	SMTPLocalPlaintext                                                                                               bool
	DataEncryptionKey, SourceAllowedHosts, DaDataToken, ModelReportsDir, TrainingURL, TrainingToken, CategorizerMode string
}

func Load() Config {
	return Config{
		IntegrationSandbox: env("INTEGRATION_SANDBOX", "false") == "true",
		FNSHubURL:          env("FNS_HUB_URL", ""), FNSHubToken: env("FNS_HUB_TOKEN", ""), FNSHubCompany: env("FNS_HUB_COMPANY", ""),
		TrustedProxyCIDRs: strings.FieldsFunc(env("TRUSTED_PROXY_CIDRS", ""), func(r rune) bool { return r == ',' || r == ' ' }),
		HTTPAddr:          env("HTTP_ADDR", ":8080"),
		DatabaseURL:       env("DATABASE_URL", ""),
		MLAddr:            env("ML_ADDR", "localhost:50051"),
		MLTimeout:         duration("ML_TIMEOUT", 5*time.Second),
		JWTSecret:         env("JWT_SECRET", ""),
		LogLevel:          env("LOG_LEVEL", "info"),
		PublicURL:         strings.TrimRight(env("PUBLIC_URL", "http://localhost:8080"), "/"),
		FrontendURL:       strings.TrimRight(env("FRONTEND_URL", "http://localhost:3000"), "/"),
		CookieSecure:      env("COOKIE_SECURE", "true") != "false",
		GoogleClientID:    env("GOOGLE_CLIENT_ID", ""), GoogleClientSecret: env("GOOGLE_CLIENT_SECRET", ""),
		YandexClientID: env("YANDEX_CLIENT_ID", ""), YandexClientSecret: env("YANDEX_CLIENT_SECRET", ""),
		SMTPAddr: env("SMTP_ADDR", ""), SMTPUser: env("SMTP_USER", ""), SMTPPassword: env("SMTP_PASSWORD", ""), SMTPFrom: env("SMTP_FROM", ""),
		SMTPLocalPlaintext: env("SMTP_LOCAL_PLAINTEXT", "false") == "true",
		DataEncryptionKey:  env("DATA_ENCRYPTION_KEY", ""), SourceAllowedHosts: env("SOURCE_ALLOWED_HOSTS", ""), DaDataToken: env("DADATA_API_TOKEN", ""), ModelReportsDir: env("MODEL_REPORTS_DIR", "../ml/reports/metrics"), TrainingURL: env("TRAINING_URL", ""), TrainingToken: env("TRAINING_TOKEN", ""), CategorizerMode: env("CATEGORIZER_MODE", "rules"),
	}
}

// ValidatePlatform validates fixed redirect origins and prevents insecure remote cookies.
func (c Config) ValidatePlatform() error {
	for _, cidr := range c.TrustedProxyCIDRs {
		_, network, err := net.ParseCIDR(cidr)
		if err != nil {
			return fmt.Errorf("invalid TRUSTED_PROXY_CIDRS")
		}
		ones, _ := network.Mask.Size()
		if ones == 0 {
			return fmt.Errorf("TRUSTED_PROXY_CIDRS must not trust every address")
		}
	}
	if len(c.JWTSecret) < 32 {
		return fmt.Errorf("JWT_SECRET must contain at least 32 bytes")
	}
	for _, raw := range []string{c.PublicURL, c.FrontendURL} {
		u, err := url.Parse(raw)
		if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" || u.Opaque != "" {
			return fmt.Errorf("PUBLIC_URL and FRONTEND_URL must be origins without paths")
		}
		local := u.Hostname() == "localhost" || net.ParseIP(u.Hostname()) != nil && net.ParseIP(u.Hostname()).IsLoopback()
		if u.Scheme != "https" && !(u.Scheme == "http" && local) {
			return fmt.Errorf("remote public URLs require HTTPS")
		}
		if !c.CookieSecure && !local {
			return fmt.Errorf("COOKIE_SECURE=false is allowed only for loopback URLs")
		}
	}
	if (c.GoogleClientID == "") != (c.GoogleClientSecret == "") || (c.YandexClientID == "") != (c.YandexClientSecret == "") {
		return fmt.Errorf("OAuth requires both client ID and secret")
	}
	if c.SMTPAddr != "" {
		host, _, err := net.SplitHostPort(c.SMTPAddr)
		if err != nil {
			return fmt.Errorf("SMTP_ADDR must be host:port")
		}
		if _, err = mail.ParseAddress(c.SMTPFrom); err != nil {
			return fmt.Errorf("SMTP_FROM must be a mailbox")
		}
		ip := net.ParseIP(host)
		if c.SMTPLocalPlaintext && host != "localhost" && (ip == nil || !ip.IsLoopback()) {
			return fmt.Errorf("plaintext SMTP is allowed only on loopback")
		}
	}
	return nil
}

func env(k, def string) string {
	if v, ok := os.LookupEnv(k); ok {
		return v
	}
	return def
}

func duration(k string, def time.Duration) time.Duration {
	if d, err := time.ParseDuration(os.Getenv(k)); err == nil {
		return d
	}
	return def
}
