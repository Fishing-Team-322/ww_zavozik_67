package config

import (
	"strings"
	"testing"
)

func TestPlatformOriginsAndSecrets(t *testing.T) {
	valid := Config{JWTSecret: strings.Repeat("x", 32), PublicURL: "https://api.example.com", FrontendURL: "https://app.example.com", CookieSecure: true}
	if err := valid.ValidatePlatform(); err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"short_secret", "remote_http", "remote_cookie", "redirect_userinfo", "redirect_path", "smtp_plaintext", "incomplete_oauth"} {
		c := valid
		switch kind {
		case "short_secret":
			c.JWTSecret = "short"
		case "remote_http":
			c.PublicURL = "http://api.example.com"
		case "remote_cookie":
			c.CookieSecure = false
		case "redirect_userinfo":
			c.FrontendURL = "https://user:password@app.example.com"
		case "redirect_path":
			c.FrontendURL = "https://app.example.com/path"
		case "smtp_plaintext":
			c.SMTPAddr = "mail.example.com:25"
			c.SMTPFrom = "no-reply@example.com"
			c.SMTPLocalPlaintext = true
		case "incomplete_oauth":
			c.GoogleClientID = "id"
		}
		if err := c.ValidatePlatform(); err == nil {
			t.Fatalf("accepted %s", kind)
		}
	}
	valid.PublicURL = "http://localhost:8080"
	valid.FrontendURL = "http://127.0.0.1:3000"
	valid.CookieSecure = false
	if err := valid.ValidatePlatform(); err != nil {
		t.Fatal(err)
	}
}
