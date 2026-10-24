package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
)

type platformKey int

const (
	requestKey platformKey = iota
	principalKey
	bodyKey
)

func request(ctx context.Context) *http.Request { return ctx.Value(requestKey).(*http.Request) }
func principal(ctx context.Context) platform.Principal {
	return ctx.Value(principalKey).(platform.Principal)
}
func rawBody(ctx context.Context) map[string]json.RawMessage {
	v, _ := ctx.Value(bodyKey).(map[string]json.RawMessage)
	return v
}

type attempt struct {
	count int
	until time.Time
}
type limiter struct {
	mu      sync.Mutex
	entries map[string]attempt
}

func (l *limiter) allow(key string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := time.Now()
	if len(l.entries) >= 10000 {
		for k, v := range l.entries {
			if !v.until.After(now) {
				delete(l.entries, k)
			}
		}
	}
	a, exists := l.entries[key]
	if !exists && len(l.entries) >= 10000 {
		return false
	}
	if !a.until.After(now) {
		a = attempt{until: now.Add(time.Minute)}
	}
	a.count++
	l.entries[key] = a
	return a.count <= 30
}
func (s *Server) withPlatform(next http.Handler) http.Handler {
	limits := &limiter{entries: map[string]attempt{}}
	expensive := make(chan struct{}, 4)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		if strings.HasPrefix(r.URL.Path, "/v1/") {
			w.Header().Set("Cache-Control", "no-store")
		}
		if s.Accounts != nil {
			origin := r.Header.Get("Origin")
			if origin != "" {
				w.Header().Add("Vary", "Origin")
				if origin != s.Accounts.FrontendURL {
					writeError(w, 403, "origin_forbidden", "Недопустимый источник запроса")
					return
				}
				w.Header().Set("Access-Control-Allow-Origin", origin)
				w.Header().Set("Access-Control-Allow-Credentials", "true")
			}
			if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
				w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PATCH, PUT, DELETE, OPTIONS")
				w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type")
				w.Header().Set("Access-Control-Max-Age", "600")
				w.WriteHeader(204)
				return
			}
		}
		*r = *r.WithContext(context.WithValue(r.Context(), requestKey, r))
		isAuth := strings.HasPrefix(r.URL.Path, "/v1/auth/")
		public := r.URL.Path == "/healthz" || r.URL.Path == "/v1/models" || r.URL.Path == "/v1/models/quality" || (isAuth && r.URL.Path != "/v1/auth/logout")
		if strings.HasPrefix(r.URL.Path, "/v1/") && !public {
			if s.Accounts == nil {
				writeError(w, 503, "platform_unavailable", "Хранение аккаунтов пока не настроено")
				return
			}
			parts := strings.Fields(r.Header.Get("Authorization"))
			if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
				w.Header().Set("WWW-Authenticate", "Bearer")
				writeError(w, 401, "unauthorized", "Войдите в аккаунт")
				return
			}
			p, err := s.Accounts.Authenticate(r.Context(), parts[1])
			if err != nil {
				s.platformError(w, err)
				return
			}
			*r = *r.WithContext(context.WithValue(r.Context(), principalKey, p))
		}
		if (isAuth && r.URL.Path != "/v1/auth/providers") || r.URL.Path == "/v1/me/password" {
			if s.Accounts == nil {
				writeError(w, 503, "platform_unavailable", "Хранение аккаунтов пока не настроено")
				return
			}
			ip := s.clientIP(r)
			if !limits.allow(ip) {
				w.Header().Set("Retry-After", "60")
				writeError(w, 429, "rate_limited", "Слишком много попыток. Подождите минуту")
				return
			}
			select {
			case expensive <- struct{}{}:
				defer func() { <-expensive }()
			default:
				w.Header().Set("Retry-After", "1")
				writeError(w, 429, "busy", "Повторите попытку чуть позже")
				return
			}
		}
		required, allowed, check := bodyRules(r.Method, r.URL.Path)
		productJSON := !check && r.ContentLength != 0 && r.Header.Get("Content-Type") != "" && strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") && r.Method != "GET" && r.Method != "HEAD"
		if productJSON {
			check = true
		}
		if check {
			media, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
			if err != nil || media != "application/json" {
				writeError(w, 415, "unsupported_media_type", "Используйте application/json")
				return
			}
			data, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1024*1024))
			if err != nil {
				writeError(w, 413, "body_too_large", "Слишком большой запрос")
				return
			}
			values, err := objectBody(data)
			if err != nil {
				writeError(w, 400, "bad_request", "Нужен JSON-объект без повторяющихся полей")
				return
			}
			for _, key := range required {
				v, ok := values[key]
				if !ok || bytes.Equal(bytes.TrimSpace(v), []byte("null")) {
					writeError(w, 400, "bad_request", "Не заполнено поле: "+key)
					return
				}
			}
			for key, value := range values {
				if !productJSON && !strings.Contains(" "+allowed+" ", " "+key+" ") {
					writeError(w, 400, "bad_request", "Неизвестное поле запроса")
					return
				}
				if key != "inn" && bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
					writeError(w, 400, "bad_request", "Поле не может быть null: "+key)
					return
				}
			}
			if r.Method == http.MethodPatch && len(values) == 0 {
				writeError(w, 400, "bad_request", "Укажите изменяемые поля")
				return
			}
			r.Body = io.NopCloser(bytes.NewReader(data))
			*r = *r.WithContext(context.WithValue(r.Context(), bodyKey, values))
		}
		next.ServeHTTP(w, r)
	})
}
func objectBody(data []byte) (map[string]json.RawMessage, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	token, err := dec.Token()
	if err != nil || token != json.Delim('{') {
		return nil, io.ErrUnexpectedEOF
	}
	out := map[string]json.RawMessage{}
	for dec.More() {
		key, err := dec.Token()
		if err != nil {
			return nil, err
		}
		name, ok := key.(string)
		if !ok {
			return nil, io.ErrUnexpectedEOF
		}
		if _, ok = out[name]; ok {
			return nil, io.ErrUnexpectedEOF
		}
		var value json.RawMessage
		if err = dec.Decode(&value); err != nil {
			return nil, err
		}
		out[name] = value
	}
	if _, err = dec.Token(); err != nil {
		return nil, err
	}
	if _, err = dec.Token(); err != io.EOF {
		return nil, io.ErrUnexpectedEOF
	}
	return out, nil
}
func bodyRules(method, path string) (required []string, allowed string, ok bool) {
	route := method + " " + path
	switch route {
	case "POST /v1/auth/register":
		return []string{"email", "password", "consent_pd"}, "email password consent_pd", true
	case "POST /v1/auth/login":
		return []string{"email", "password"}, "email password", true
	case "POST /v1/auth/password/forgot":
		return []string{"email"}, "email", true
	case "POST /v1/auth/password/reset":
		return []string{"token", "new_password"}, "token new_password", true
	case "PATCH /v1/me/password":
		return []string{"old_password", "new_password"}, "old_password new_password", true
	case "POST /v1/companies":
		return []string{"name", "legal_form", "industry"}, "name inn legal_form industry tax_regime reserve default_horizon", true
	}
	parts := strings.Split(strings.Trim(path, "/"), "/")
	if len(parts) >= 3 && parts[0] == "v1" && parts[1] == "companies" {
		if len(parts) == 3 && method == "PATCH" {
			return nil, "name inn legal_form industry tax_regime reserve default_horizon", true
		}
		if len(parts) == 3 && method == "DELETE" {
			return []string{"confirm_name"}, "confirm_name", true
		}
		if len(parts) == 4 && parts[3] == "state" && method == "PUT" {
			return []string{"expected_version", "data"}, "expected_version data", true
		}
	}
	return nil, "", false
}
