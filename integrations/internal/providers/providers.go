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

func List(oneCODataConfigured, daDataConfigured bool, marketplaces ...bool) []Status {
	oneCODataStatus := "not_configured"
	if oneCODataConfigured {
		oneCODataStatus = "ready"
	}
	daDataStatus := "not_configured"
	if daDataConfigured {
		daDataStatus = "ready"
	}
	wbStatus, ozonStatus := "mock_ready", "mock_ready"
	if len(marketplaces) > 0 && marketplaces[0] {
		wbStatus = "ready"
	}
	if len(marketplaces) > 1 && marketplaces[1] {
		ozonStatus = "ready"
	}
	return []Status{
		{"onecbank", "file", "ready"},
		{"onecodata", "pull", oneCODataStatus},
		{"dadata", "lookup", daDataStatus},
		{"fnsopendata", "archive_import", "ready"},
		{"wb", "pull", wbStatus},
		{"ozon", "pull", ozonStatus},
		{"csv", "file", "ready"},
	}
}
