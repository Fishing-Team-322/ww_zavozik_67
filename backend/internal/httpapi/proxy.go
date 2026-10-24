package httpapi

import (
	"net"
	"net/http"
	"strings"
)

func (s *Server) trustedIP(ip net.IP) bool {
	for _, cidr := range s.TrustedProxyCIDRs {
		_, network, err := net.ParseCIDR(cidr)
		if err == nil && network.Contains(ip) {
			return true
		}
	}
	return false
}

// Walk from the socket toward the client, stopping at the first untrusted hop.
// An untrusted socket cannot choose its limiter key by sending forwarding headers.
func (s *Server) clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	current := net.ParseIP(host)
	if current == nil || !s.trustedIP(current) {
		return host
	}
	forwarded := strings.Split(r.Header.Get("X-Forwarded-For"), ",")
	if len(forwarded) > 16 {
		return host
	}
	for i := len(forwarded) - 1; i >= 0; i-- {
		if !s.trustedIP(current) {
			break
		}
		next := net.ParseIP(strings.TrimSpace(forwarded[i]))
		if next == nil {
			return host
		}
		current = next
	}
	return current.String()
}
