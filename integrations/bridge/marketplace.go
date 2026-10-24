package bridge

import (
	"context"
	"net/http"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/ozon"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/wb"
)

type WBEntry = wb.Entry
type OzonEntry = ozon.Entry

var wbLimiter = &wb.Limiter{}

func FetchWB(ctx context.Context, token, from, to string, client *http.Client) ([]WBEntry, error) {
	return (wb.Client{Token: token, HTTP: client, Limiter: wbLimiter}).Fetch(ctx, from, to)
}
func FetchWBMode(ctx context.Context, token, from, to string, client *http.Client, sandbox bool) ([]WBEntry, error) {
	if sandbox {
		return (wb.Client{Token: token, HTTP: client, EndpointURL: wb.Endpoint}).Fetch(ctx, from, to)
	}
	return FetchWB(ctx, token, from, to, client)
}
func FetchOzon(ctx context.Context, id, key string, from, to time.Time, client *http.Client) ([]OzonEntry, error) {
	return (ozon.Client{ClientID: id, APIKey: key, HTTP: client}).Fetch(ctx, from, to)
}
