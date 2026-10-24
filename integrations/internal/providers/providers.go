package providers

import (
	"context"
	"io"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
)

type FileParser interface {
	Kind() string
	Parse(context.Context, io.Reader, contracts.Identity) (contracts.ImportBatch, error)
}

type Puller interface {
	Kind() string
	Fetch(context.Context, contracts.Identity) (contracts.ImportBatch, error)
}

type Status struct {
	Kind   string `json:"kind"`
	Mode   string `json:"mode"`
	Status string `json:"status"`
}

func List(oneCODataConfigured, daDataConfigured bool) []Status {
	oneCODataStatus := "not_configured"
	if oneCODataConfigured {
		oneCODataStatus = "ready"
	}
	daDataStatus := "not_configured"
	if daDataConfigured {
		daDataStatus = "ready"
	}
	return []Status{
		{"onecbank", "file", "ready"},
		{"onecodata", "pull", oneCODataStatus},
		{"dadata", "lookup", daDataStatus},
		{"fnsopendata", "archive_import", "ready"},
		{"wb", "pull", "mock_ready"},
		{"ozon", "pull", "mock_ready"},
		{"csv", "file", "ready"},
	}
}
