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
