package bridge

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// The backend separately authorizes the exact operator allowlisted host:port.
// A public hostname must never resolve to a private address, including on a
// later connection. Explicit local IPs support operator approved private 1C.
func odataAddressAllowed(host string, ip net.IP) bool {
	if ip == nil || ip.IsUnspecified() || ip.IsMulticast() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() {
		return false
	}
	for _, cidr := range []string{"100.64.0.0/10", "0.0.0.0/8", "198.18.0.0/15", "240.0.0.0/4"} {
		_, reserved, _ := net.ParseCIDR(cidr)
		if reserved.Contains(ip) {
			return false
		}
	}
	if literal := net.ParseIP(host); literal != nil {
		return literal.Equal(ip)
	}
	if strings.EqualFold(host, "localhost") {
		return ip.IsLoopback()
	}
	return ip.IsGlobalUnicast() && !ip.IsPrivate() && !ip.IsLoopback()
}

func odataHTTP(root string) *http.Client {
	parsed, _ := url.Parse(root)
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	transport.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		host, port, e := net.SplitHostPort(address)
		if e != nil || parsed == nil || !strings.EqualFold(host, parsed.Hostname()) {
			return nil, errors.New("OData destination rejected")
		}
		ips, e := net.DefaultResolver.LookupIPAddr(ctx, host)
		if e != nil || len(ips) == 0 {
			return nil, errors.New("OData address unavailable")
		}
		for _, ip := range ips {
			if !odataAddressAllowed(host, ip.IP) {
				return nil, errors.New("OData destination rejected")
			}
		}
		dialer := net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}
		var last error
		for _, ip := range ips {
			var c net.Conn
			c, last = dialer.DialContext(ctx, network, net.JoinHostPort(ip.IP.String(), port))
			if last == nil {
				return c, nil
			}
		}
		return nil, last
	}
	return &http.Client{Transport: transport, Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}
