package onecodata

import (
	"context"
	"net/http"
	"strings"
	"time"
)

type AccountingAccount struct {
	Number           string `json:"number"`
	Name             string `json:"name"`
	VerifiedInSource bool   `json:"verified_in_source"`
}
type AccountingOrganization struct {
	Name     string              `json:"name"`
	INN      string              `json:"inn"`
	Accounts []AccountingAccount `json:"accounts"`
}

// DiscoverAccounting lists only accounts owned by the requested INN in this publication.
func (c Client) DiscoverAccounting(ctx context.Context, root, inn string) ([]AccountingOrganization, error) {
	if _, err := c.Inspect(ctx, root); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	client := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if c.HTTP != nil {
		client.Transport = c.HTTP.Transport
	}
	orgs, err := c.planRows(ctx, client, root, "Catalog_Организации")
	if err != nil {
		return nil, err
	}
	accounts, err := c.planRows(ctx, client, root, "Catalog_БанковскиеСчета")
	if err != nil {
		return nil, err
	}
	out := []AccountingOrganization{}
	for _, org := range orgs {
		if getString(org, "ИНН") != inn || getString(org, "DeletionMark") == "true" {
			continue
		}
		item := AccountingOrganization{Name: getString(org, "Description"), INN: inn, Accounts: []AccountingAccount{}}
		for _, row := range accounts {
			number := getString(row, "НомерСчета")
			if getString(row, "Owner") == getString(org, "Ref_Key") && strings.HasSuffix(getString(row, "Owner_Type"), "Catalog_Организации") && len(number) == 20 && digits(number) && strings.Trim(number, "0") != "" && getString(row, "DeletionMark") != "true" {
				item.Accounts = append(item.Accounts, AccountingAccount{Number: number, Name: getString(row, "Description"), VerifiedInSource: true})
			}
		}
		out = append(out, item)
	}
	return out, nil
}
