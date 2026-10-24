package httpapi

import (
	"net/http/httptest"
	"testing"
)

func TestProxyClientAddressCannotBeSpoofed(t *testing.T) {
	s := &Server{TrustedProxyCIDRs: []string{"172.30.0.0/24"}}
	for _, tc := range []struct{ socket, forwarded, want string }{
		{"198.51.100.9:123", "1.1.1.1", "198.51.100.9"},
		{"172.30.0.2:123", "198.51.100.9", "198.51.100.9"},
		{"172.30.0.2:123", "1.1.1.1, 198.51.100.9", "198.51.100.9"},
		{"172.30.0.2:123", "198.51.100.9, 172.30.0.3", "198.51.100.9"},
		{"172.30.0.2:123", "bad", "172.30.0.2"},
	} {
		r := httptest.NewRequest("POST", "/v1/auth/login", nil)
		r.RemoteAddr = tc.socket
		r.Header.Set("X-Forwarded-For", tc.forwarded)
		if got := s.clientIP(r); got != tc.want {
			t.Errorf("%s / %s: %s want %s", tc.socket, tc.forwarded, got, tc.want)
		}
	}
}

func TestSessionTrafficKeepsCredentialRateBudgetIsolated(t *testing.T) {
	l := &limiter{entries: map[string]attempt{}}
	session, limit := authRateBudget("/v1/auth/refresh", "198.51.100.9")
	for i := 0; i < limit; i++ {
		if !l.allowLimit(session, limit) {
			t.Fatal("session budget exhausted early")
		}
	}
	if l.allowLimit(session, limit) {
		t.Fatal("session traffic is unbounded")
	}
	login, limit := authRateBudget("/v1/auth/login", "198.51.100.9")
	for i := 0; i < 30; i++ {
		if !l.allowLimit(login, limit) {
			t.Fatal("refresh consumed password attempts")
		}
	}
	if l.allowLimit(login, limit) {
		t.Fatal("password attempt budget weakened")
	}
	other, limit := authRateBudget("/v1/auth/login", "198.51.100.10")
	if !l.allowLimit(other, limit) {
		t.Fatal("another client blocked")
	}
}
