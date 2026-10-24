package bridge

import (
	"net"
	"testing"
)

func TestODataDNSBoundary(t *testing.T) {
	for _, tt := range []struct {
		host, ip string
		want     bool
	}{
		{"customer.example", "8.8.8.8", true},
		{"customer.example", "127.0.0.1", false},
		{"customer.example", "10.2.3.4", false},
		{"customer.example", "::1", false},
		{"customer.example", "169.254.169.254", false},
		{"customer.example", "100.100.100.200", false},
		{"169.254.169.254", "169.254.169.254", false},
		{"127.0.0.1", "127.0.0.1", true},
		{"10.2.3.4", "10.2.3.4", true},
		{"localhost", "127.0.0.1", true},
		{"localhost", "10.2.3.4", false},
	} {
		if got := odataAddressAllowed(tt.host, net.ParseIP(tt.ip)); got != tt.want {
			t.Errorf("%s -> %s: %v", tt.host, tt.ip, got)
		}
	}
}
