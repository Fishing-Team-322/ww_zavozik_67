// Package bridge exposes the integration adapters to the authenticated backend.
// Identity is supplied by the backend after checking company ownership.
package bridge

import (
	"context"
	"io"
	"net/http"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/dadata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecbank"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
)

type Identity = contracts.Identity
type Batch = contracts.ImportBatch
type Operation = contracts.Operation
type PlannedEvent = contracts.PlannedEvent
type ODataConfig = onecodata.Config
type ODataDiscovery = onecodata.Discovery
type ODataPlanConfig = onecodata.PlanConfig
type Party = dadata.Party

func ParseBank(ctx context.Context, r io.Reader, id Identity) (Batch, error) {
	return (onecbank.Parser{}).Parse(ctx, r, id)
}
func FetchOData(ctx context.Context, cfg ODataConfig, username, password string) (Batch, error) {
	return (onecodata.Client{Username: username, Password: password}).Fetch(ctx, cfg)
}
func FetchODataPlans(ctx context.Context, cfg ODataPlanConfig, username, password string) (Batch, error) {
	return (onecodata.Client{Username: username, Password: password}).FetchPlans(ctx, cfg)
}
func SuggestODataAccounting(ctx context.Context, baseURL, companyID, companyINN, account, username, password string) (ODataConfig, *ODataPlanConfig, error) {
	return (onecodata.Client{Username: username, Password: password}).SuggestAccounting(ctx, baseURL, companyID, companyINN, account)
}
func InspectOData(ctx context.Context, baseURL, username, password string) (ODataDiscovery, error) {
	return (onecodata.Client{Username: username, Password: password}).Inspect(ctx, baseURL)
}
func Lookup(ctx context.Context, token, inn string, httpClient *http.Client) (Party, error) {
	return (dadata.Client{Token: token, HTTP: httpClient}).Lookup(ctx, inn)
}
