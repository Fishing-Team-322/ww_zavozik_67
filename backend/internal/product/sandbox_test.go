package product

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/config"
	"testing"
)

func TestSandboxIsForbiddenOnRemoteOrigins(t *testing.T) {
	if _, e := New(nil, config.Config{IntegrationSandbox: true, PublicURL: "https://public.example", FrontendURL: "https://public.example"}, nil); e == nil {
		t.Fatal("public sandbox accepted")
	}
}
