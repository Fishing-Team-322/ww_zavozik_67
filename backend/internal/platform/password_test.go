package platform

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func TestPasswordHashAndMalformedCosts(t *testing.T) {
	hash, err := HashPassword("пароль из восьми символов")
	if err != nil {
		t.Fatal(err)
	}
	if !CheckPassword(hash, "пароль из восьми символов") || CheckPassword(hash, "другой пароль") {
		t.Fatal("password verification")
	}
	another, err := HashPassword("пароль из восьми символов")
	if err != nil || another == hash {
		t.Fatal("salt reuse", err)
	}
	for _, value := range []string{"", strings.Replace(hash, "m=65536", "m=999999999", 1), strings.Replace(hash, "v=19", "v=18", 1), hash + "$junk"} {
		if CheckPassword(value, "пароль из восьми символов") {
			t.Fatal("accepted malformed hash")
		}
	}
	for _, p := range []string{"short", strings.Repeat("x", 257)} {
		if ValidatePassword(p) == nil {
			t.Fatal("accepted invalid password")
		}
	}
}

type principalSpy struct {
	Repository
	calls int
}

func (s *principalSpy) Principal(context.Context, string, string) (Principal, error) {
	s.calls++
	return Principal{}, nil
}
func TestJWTRejectsInvalidClaimsBeforeStorage(t *testing.T) {
	spy := &principalSpy{}
	s := &Service{Secret: []byte(strings.Repeat("x", 32)), Repo: spy}
	base := claims{SessionID: "session", RegisteredClaims: jwt.RegisteredClaims{Subject: "user", Issuer: "zavozik", Audience: jwt.ClaimStrings{"zavozik-api"}, IssuedAt: jwt.NewNumericDate(time.Now()), ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Minute))}}
	for _, kind := range []string{"signature", "expired", "audience", "issuer", "missing_expiry", "future_issued", "algorithm"} {
		c := base
		key := s.Secret
		method := jwt.SigningMethodHS256
		switch kind {
		case "signature":
			key = []byte(strings.Repeat("z", 32))
		case "expired":
			c.ExpiresAt = jwt.NewNumericDate(time.Now().Add(-time.Minute))
		case "audience":
			c.Audience = jwt.ClaimStrings{"other-api"}
		case "issuer":
			c.Issuer = "other-app"
		case "missing_expiry":
			c.ExpiresAt = nil
		case "future_issued":
			c.IssuedAt = jwt.NewNumericDate(time.Now().Add(time.Hour))
		case "algorithm":
			method = jwt.SigningMethodHS384
		}
		token, err := jwt.NewWithClaims(method, c).SignedString(key)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = s.Authenticate(context.Background(), token); !IsStatus(err, 401) {
			t.Fatalf("accepted %s: %v", kind, err)
		}
	}
	if spy.calls != 0 {
		t.Fatal("invalid JWT reached storage")
	}
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, base).SignedString(s.Secret)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Authenticate(context.Background(), token); err != nil || spy.calls != 1 {
		t.Fatal("valid JWT", err, spy.calls)
	}
}
