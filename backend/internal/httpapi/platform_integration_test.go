package httpapi_test

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/httpapi"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/migrations"
	"github.com/getkin/kin-openapi/openapi3"
	"github.com/getkin/kin-openapi/openapi3filter"
	"github.com/getkin/kin-openapi/routers"
	"github.com/getkin/kin-openapi/routers/legacy"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"golang.org/x/oauth2"
)

type resetMail struct {
	link  string
	calls int
}

func init() {
	openapi3filter.RegisterBodyDecoder("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", openapi3filter.FileBodyDecoder)
}

func (m *resetMail) SendReset(_ context.Context, _ string, link string) error {
	m.link = link
	m.calls++
	return nil
}

type harness struct {
	t       *testing.T
	service *platform.Service
	db      *store.Postgres
	handler http.Handler
	router  routers.Router
	seq     atomic.Int64
	rawURL  string
}

func integration(t *testing.T) *harness {
	t.Helper()
	raw := os.Getenv("TEST_DATABASE_URL")
	if raw == "" {
		t.Skip("set TEST_DATABASE_URL to run isolated PostgreSQL integration tests")
	}
	ctx := context.Background()
	admin, err := pgx.Connect(ctx, raw)
	if err != nil {
		t.Fatal(err)
	}
	schema := "account_test_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, err = admin.Exec(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, e := admin.Exec(context.Background(), "DROP SCHEMA "+schema+" CASCADE")
		if e != nil {
			t.Error(e)
		}
		admin.Close(context.Background())
	})
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	q := u.Query()
	q.Set("search_path", schema)
	u.RawQuery = q.Encode()
	raw = u.String()
	cfg, err := pgx.ParseConfig(raw)
	if err != nil {
		t.Fatal(err)
	}
	sqlDB := sql.OpenDB(stdlib.GetConnector(*cfg))
	defer sqlDB.Close()
	goose.SetBaseFS(migrations.Files)
	if err = goose.SetDialect("postgres"); err != nil {
		t.Fatal(err)
	}
	if err = goose.UpContext(ctx, sqlDB, "."); err != nil {
		t.Fatal(err)
	}
	// Running the migration again must be harmless.
	if err = goose.UpContext(ctx, sqlDB, "."); err != nil {
		t.Fatal(err)
	}
	db, err := store.Open(ctx, raw)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(db.Pool.Close)
	accounts, err := platform.New(db, strings.Repeat("test-secret-", 4))
	if err != nil {
		t.Fatal(err)
	}
	accounts.FrontendURL = "http://localhost:3000"
	accounts.PublicURL = "http://localhost:8080"
	accounts.Providers = map[string]platform.Provider{}
	loader := openapi3.NewLoader()
	spec, err := loader.LoadFromFile("../../../api/openapi.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if err = spec.Validate(ctx); err != nil {
		t.Fatal(err)
	}
	// Match httptest's origin while keeping production servers unchanged.
	spec.Servers = nil
	router, err := legacy.NewRouter(spec)
	if err != nil {
		t.Fatal(err)
	}
	h := &harness{t: t, service: accounts, db: db, router: router, rawURL: raw}
	h.reopen()
	return h
}
func (h *harness) reopen() {
	h.handler = (&httpapi.Server{Accounts: h.service, Fallback: forecast.SeasonalNaive{}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}).Handler()
}
func (h *harness) call(method, path, body, token string, cookies ...*http.Cookie) *httptest.ResponseRecorder {
	h.t.Helper()
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.RemoteAddr = fmt.Sprintf("192.0.2.%d:1234", h.seq.Add(1))
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("User-Agent", "integration-device")
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	for _, c := range cookies {
		r.AddCookie(c)
	}
	out := httptest.NewRecorder()
	h.handler.ServeHTTP(out, r)
	if route, params, err := h.router.FindRoute(r); err == nil {
		input := &openapi3filter.ResponseValidationInput{RequestValidationInput: &openapi3filter.RequestValidationInput{Request: r, PathParams: params, Route: route, Options: &openapi3filter.Options{AuthenticationFunc: openapi3filter.NoopAuthenticationFunc}}, Status: out.Code, Header: out.Header(), Body: io.NopCloser(bytes.NewReader(out.Body.Bytes()))}
		if err = openapi3filter.ValidateResponse(context.Background(), input); err != nil {
			h.t.Errorf("contract %s %s status %d: %v\n%s", method, path, out.Code, err, out.Body)
		}
	}
	return out
}
func status(t *testing.T, r *httptest.ResponseRecorder, want int) {
	t.Helper()
	if r.Code != want {
		t.Fatalf("status %d, want %d: %s", r.Code, want, r.Body)
	}
}
func decode[T any](t *testing.T, r *httptest.ResponseRecorder) T {
	t.Helper()
	var v T
	if err := json.Unmarshal(r.Body.Bytes(), &v); err != nil {
		t.Fatal(err)
	}
	return v
}
func cookie(t *testing.T, r *httptest.ResponseRecorder, name string) *http.Cookie {
	t.Helper()
	for _, c := range r.Result().Cookies() {
		if c.Name == name {
			return c
		}
	}
	t.Fatalf("missing %s cookie", name)
	return nil
}
func (h *harness) register(email string) (string, *http.Cookie) {
	h.t.Helper()
	r := h.call("POST", "/v1/auth/register", `{"email":"`+email+`","password":"correct password 123","consent_pd":true}`, "")
	status(h.t, r, 201)
	return decode[platform.Token](h.t, r).AccessToken, cookie(h.t, r, "zavozik_refresh")
}

func TestPlatformIntegration(t *testing.T) {
	h := integration(t)
	ctx := context.Background()
	owner, refresh := h.register(" Owner@Example.com ")
	outsider, _ := h.register("other@example.com")
	if !refresh.HttpOnly || refresh.SameSite != http.SameSiteLaxMode {
		t.Fatal("unsafe refresh cookie")
	}
	me := h.call("GET", "/v1/me", "", owner)
	status(t, me, 200)
	if strings.Contains(me.Body.String(), "password") || !strings.Contains(me.Body.String(), `"email":"owner@example.com"`) {
		t.Fatal(me.Body.String())
	}
	status(t, h.call("POST", "/v1/auth/register", `{"email":"OWNER@example.com","password":"correct password 123","consent_pd":true}`, ""), 409)
	status(t, h.call("POST", "/v1/auth/register", `{"email":"new@example.com","password":"correct password 123","consent_pd":false}`, ""), 400)
	status(t, h.call("POST", "/v1/auth/login", `{"email":"owner@example.com","password":"wrong password"}`, ""), 401)
	status(t, h.call("POST", "/v1/auth/login", `{"email":"missing@example.com","password":"wrong password"}`, ""), 401)
	status(t, h.call("GET", "/v1/me", "", "bad.jwt.token"), 401)
	status(t, h.call("GET", "/v1/companies", "", ""), 401)
	status(t, h.call("GET", "/v1/no-such-route", "", owner), 404)
	status(t, h.call("POST", "/v1/me", "", owner), 405)
	created := h.call("POST", "/v1/companies", `{"name":"Тест ООО","legal_form":"ООО","industry":"services","reserve":12345678.91}`, owner)
	status(t, created, 201)
	company := decode[platform.Company](t, created)
	base := "/v1/companies/" + company.ID
	if company.Reserve != 12345678.91 {
		t.Fatal("money precision lost", company.Reserve)
	}
	status(t, h.call("GET", base, "", owner), 200)
	status(t, h.call("GET", base, "", outsider), 404)
	status(t, h.call("PATCH", base, `{"name":"stolen"}`, outsider), 404)
	status(t, h.call("DELETE", base, `{"confirm_name":"Тест ООО"}`, outsider), 404)
	status(t, h.call("GET", base+"/state", "", outsider), 404)
	status(t, h.call("PUT", base+"/state", `{"expected_version":0,"data":{}}`, outsider), 404)
	otherList := h.call("GET", "/v1/companies", "", outsider)
	status(t, otherList, 200)
	if otherList.Body.String() != "[]\n" {
		t.Fatal(otherList.Body.String())
	}
	status(t, h.call("PATCH", base, `{"inn":"6164138513","default_horizon":60}`, owner), 200)
	updated := h.call("PATCH", base, `{"inn":null}`, owner)
	status(t, updated, 200)
	if decode[platform.Company](t, updated).INN != nil {
		t.Fatal("INN not cleared")
	}
	initial := h.call("GET", base+"/state", "", owner)
	status(t, initial, 200)
	if decode[platform.State](t, initial).Version != 0 {
		t.Fatal("initial version")
	}
	state := h.call("PUT", base+"/state", `{"expected_version":0,"data":{"draft":"hello","large_id":9007199254740993}}`, owner)
	status(t, state, 200)
	if !strings.Contains(state.Body.String(), "9007199254740993") {
		t.Fatal("state integer precision lost")
	}
	status(t, h.call("PUT", base+"/state", `{"expected_version":0,"data":{"draft":"lost"}}`, owner), 409)
	// Reopening the pool and server proves state is not process-local memory.
	db2, err := store.Open(ctx, h.rawURL)
	if err != nil {
		t.Fatal(err)
	}
	h.service.Repo = db2
	h.reopen()
	persisted := h.call("GET", base+"/state", "", owner)
	status(t, persisted, 200)
	if !strings.Contains(persisted.Body.String(), "hello") {
		t.Fatal(persisted.Body.String())
	}
	h.service.Repo = h.db
	db2.Pool.Close()
	h.reopen()
	var wg sync.WaitGroup
	results := make(chan int, 2)
	for range 2 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			results <- h.call("PUT", base+"/state", `{"expected_version":1,"data":{"winner":true}}`, owner).Code
		}()
	}
	wg.Wait()
	close(results)
	counts := map[int]int{}
	for code := range results {
		counts[code]++
	}
	if counts[200] != 1 || counts[409] != 1 {
		t.Fatal("concurrent writes", counts)
	}
	// Another login/device sees the same company, with an independent session.
	login := h.call("POST", "/v1/auth/login", `{"email":"owner@example.com","password":"correct password 123"}`, "")
	status(t, login, 200)
	device2 := decode[platform.Token](t, login).AccessToken
	status(t, h.call("GET", base+"/state", "", device2), 200)
	sessions := h.call("GET", "/v1/me/sessions", "", owner)
	status(t, sessions, 200)
	ss := decode[[]platform.Session](t, sessions)
	if len(ss) != 2 {
		t.Fatal("sessions", ss)
	}
	var current string
	for _, s := range ss {
		if s.Current {
			current = s.ID
		}
	}
	status(t, h.call("DELETE", "/v1/me/sessions/"+current, "", outsider), 404)
	rotated := h.call("POST", "/v1/auth/refresh", "", "", refresh)
	status(t, rotated, 200)
	fresh := decode[platform.Token](t, rotated).AccessToken
	status(t, h.call("POST", "/v1/auth/refresh", "", "", refresh), 401)
	status(t, h.call("POST", "/v1/auth/logout", "", fresh), 204)
	status(t, h.call("GET", "/v1/me", "", owner), 401)
	status(t, h.call("GET", "/v1/me", "", device2), 200)
	// Password change revokes every session and invalidates the previous password.
	status(t, h.call("PATCH", "/v1/me/password", `{"old_password":"correct password 123","new_password":"new correct password 456"}`, device2), 204)
	status(t, h.call("GET", "/v1/me", "", device2), 401)
	status(t, h.call("POST", "/v1/auth/login", `{"email":"owner@example.com","password":"correct password 123"}`, ""), 401)
	login = h.call("POST", "/v1/auth/login", `{"email":"owner@example.com","password":"new correct password 456"}`, "")
	status(t, login, 200)
	owner = decode[platform.Token](t, login).AccessToken
	status(t, h.call("POST", "/v1/auth/password/forgot", `{"email":"owner@example.com"}`, ""), 503)
	mail := &resetMail{}
	h.service.Mailer = mail
	status(t, h.call("POST", "/v1/auth/password/forgot", `{"email":"owner@example.com"}`, ""), 204)
	status(t, h.call("POST", "/v1/auth/password/forgot", `{"email":"missing@example.com"}`, ""), 204)
	if mail.calls != 1 || !strings.HasPrefix(mail.link, "http://localhost:3000/reset-password#token=") {
		t.Fatal("mail", mail)
	}
	reset := strings.Split(mail.link, "#token=")[1]
	payload := `{"token":"` + reset + `","new_password":"restored password 789"}`
	status(t, h.call("POST", "/v1/auth/password/reset", payload, ""), 204)
	status(t, h.call("POST", "/v1/auth/password/reset", payload, ""), 400)
	status(t, h.call("GET", "/v1/me", "", owner), 401)
	login = h.call("POST", "/v1/auth/login", `{"email":"owner@example.com","password":"restored password 789"}`, "")
	status(t, login, 200)
	owner = decode[platform.Token](t, login).AccessToken
	status(t, h.call("DELETE", base, `{"confirm_name":"wrong"}`, owner), 400)
	status(t, h.call("DELETE", base, `{"confirm_name":"Тест ООО"}`, owner), 204)
	status(t, h.call("GET", base+"/state", "", owner), 404)
	var count int
	if err = h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM company_state WHERE company_id=$1", company.ID).Scan(&count); err != nil || count != 0 {
		t.Fatal("cascade", count, err)
	}

	t.Run("validation", func(t *testing.T) {
		for _, body := range []string{`{}`, `null`, `[]`, `{"email":"a@b.com","password":"password1","consent_pd":true,"role":"admin"}`, `{"email":"a@b.com","email":"other@b.com","password":"password1","consent_pd":true}`, `{"email":null,"password":"password1","consent_pd":true}`} {
			status(t, h.call("POST", "/v1/auth/register", body, ""), 400)
		}
		r := httptest.NewRequest("POST", "/v1/auth/refresh", nil)
		r.Header.Set("Origin", "https://evil.example")
		out := httptest.NewRecorder()
		h.handler.ServeHTTP(out, r)
		status(t, out, 403)
		r = httptest.NewRequest("OPTIONS", "/v1/me", nil)
		r.Header.Set("Origin", h.service.FrontendURL)
		r.Header.Set("Access-Control-Request-Method", "GET")
		out = httptest.NewRecorder()
		h.handler.ServeHTTP(out, r)
		status(t, out, 204)
		if out.Header().Get("Access-Control-Allow-Credentials") != "true" {
			t.Fatal("CORS")
		}
		r = httptest.NewRequest("POST", "/v1/auth/login", strings.NewReader(`{}`))
		out = httptest.NewRecorder()
		h.handler.ServeHTTP(out, r)
		status(t, out, 415)
		r = httptest.NewRequest("POST", "/v1/auth/login", strings.NewReader(strings.Repeat("x", 1024*1024+1)))
		r.Header.Set("Content-Type", "application/json")
		out = httptest.NewRecorder()
		h.handler.ServeHTTP(out, r)
		status(t, out, 413)
		for range 31 {
			r = httptest.NewRequest("POST", "/v1/auth/login", strings.NewReader(`{}`))
			r.Header.Set("Content-Type", "application/json")
			r.RemoteAddr = "198.51.100.1:123"
			out = httptest.NewRecorder()
			h.handler.ServeHTTP(out, r)
		}
		status(t, out, 429)
	})
	t.Run("oauth", func(t *testing.T) { testOAuth(t, h) })
}

func testOAuth(t *testing.T, h *harness) {
	var mu sync.Mutex
	var verifier string
	email := "oauth@example.com"
	subject := "google-user-1"
	verified := true
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/token" {
			if err := r.ParseForm(); err != nil {
				t.Error(err)
			}
			verifier = r.Form.Get("code_verifier")
			if verifier == "" || r.Form.Get("grant_type") != "authorization_code" {
				t.Error("missing PKCE")
			}
			io.WriteString(w, `{"access_token":"provider-secret-token","token_type":"Bearer"}`)
			return
		}
		if r.Header.Get("Authorization") != "Bearer provider-secret-token" {
			t.Error("provider token header")
		}
		json.NewEncoder(w).Encode(map[string]any{"sub": subject, "email": email, "email_verified": verified})
	}))
	defer provider.Close()
	h.service.Providers["google"] = platform.Provider{Config: oauth2.Config{ClientID: "test-client", ClientSecret: "test-secret", RedirectURL: "http://localhost:8080/v1/auth/oauth/google/callback", Scopes: []string{"openid", "email"}, Endpoint: oauth2.Endpoint{AuthURL: provider.URL + "/authorize", TokenURL: provider.URL + "/token", AuthStyle: oauth2.AuthStyleInParams}}, UserInfoURL: provider.URL + "/userinfo"}
	status(t, h.call("GET", "/v1/auth/oauth/yandex/start?consent_pd=true", "", ""), 404)
	start := func() (*http.Cookie, string, string) {
		r := h.call("GET", "/v1/auth/oauth/google/start?consent_pd=true", "", "")
		status(t, r, 302)
		u, err := url.Parse(r.Header().Get("Location"))
		if err != nil {
			t.Fatal(err)
		}
		return cookie(t, r, "zavozik_oauth_state"), u.Query().Get("state"), u.Query().Get("code_challenge")
	}
	c, state, challenge := start()
	status(t, h.call("GET", "/v1/auth/oauth/google/callback?code=test-code&state=wrong", "", "", c), 400)
	finished := h.call("GET", "/v1/auth/oauth/google/callback?code=test-code&state="+state, "", "", c)
	status(t, finished, 302)
	mu.Lock()
	sum := sha256.Sum256([]byte(verifier))
	actualChallenge := base64.RawURLEncoding.EncodeToString(sum[:])
	mu.Unlock()
	if actualChallenge != challenge || challenge == "" {
		t.Fatal("missing challenge")
	}
	if finished.Header().Get("Location") != "http://localhost:3000/auth/callback" || strings.Contains(finished.Header().Get("Location"), "token") {
		t.Fatal("token in redirect")
	}
	status(t, h.call("POST", "/v1/auth/refresh", "", "", cookie(t, finished, "zavozik_refresh")), 200)
	status(t, h.call("GET", "/v1/auth/oauth/google/callback?code=test-code&state="+state, "", "", c), 400)
	mu.Lock()
	subject = "google-user-collision"
	email = "owner@example.com"
	mu.Unlock()
	c, state, _ = start()
	status(t, h.call("GET", "/v1/auth/oauth/google/callback?code=test-code&state="+state, "", "", c), 409)
	mu.Lock()
	subject = "google-user-unverified"
	email = "unverified@example.com"
	verified = false
	mu.Unlock()
	c, state, _ = start()
	status(t, h.call("GET", "/v1/auth/oauth/google/callback?code=test-code&state="+state, "", "", c), 400)
	// Expired flows must fail before making a provider request.
	mu.Lock()
	verified = true
	mu.Unlock()
	c, state, _ = start()
	_, err := h.db.Pool.Exec(context.Background(), "UPDATE oauth_flows SET expires_at=$1 WHERE state_hash=$2", time.Now().Add(-time.Minute), platform.Digest(state))
	if err != nil {
		t.Fatal(err)
	}
	status(t, h.call("GET", "/v1/auth/oauth/google/callback?code=test-code&state="+state, "", "", c), 400)
	// Yandex uses its own profile fields and OAuth header, not Google's Bearer profile.
	yandex := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/token" {
			id, secret, ok := r.BasicAuth()
			if !ok || id != "yandex-client" || secret != "secret" {
				t.Error("Yandex client authentication")
			}
			r.ParseForm()
			if r.Form.Get("code_verifier") == "" {
				t.Error("Yandex PKCE missing")
			}
			io.WriteString(w, `{"access_token":"yandex-token","token_type":"Bearer"}`)
			return
		}
		if r.Header.Get("Authorization") != "OAuth yandex-token" {
			t.Error("Yandex profile authorization")
		}
		io.WriteString(w, `{"id":"yandex-id","default_email":"ya@example.com","client_id":"yandex-client"}`)
	}))
	defer yandex.Close()
	h.service.Providers["yandex"] = platform.Provider{Config: oauth2.Config{ClientID: "yandex-client", ClientSecret: "secret", RedirectURL: "http://localhost:8080/v1/auth/oauth/yandex/callback", Scopes: []string{"login:email"}, Endpoint: oauth2.Endpoint{AuthURL: yandex.URL + "/authorize", TokenURL: yandex.URL + "/token", AuthStyle: oauth2.AuthStyleInHeader}}, UserInfoURL: yandex.URL + "/info"}
	yaStart := h.call("GET", "/v1/auth/oauth/yandex/start?consent_pd=true", "", "")
	status(t, yaStart, 302)
	yaURL, err := url.Parse(yaStart.Header().Get("Location"))
	if err != nil {
		t.Fatal(err)
	}
	status(t, h.call("GET", "/v1/auth/oauth/yandex/callback?code=code&state="+yaURL.Query().Get("state"), "", "", cookie(t, yaStart, "zavozik_oauth_state")), 302)
}
