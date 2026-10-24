package onecodata_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
)

func TestSuggestAccountingUsesPublishedReferences(t *testing.T) {
	sets := map[string][]string{
		"Catalog_Организации":                 {"Ref_Key", "ИНН"},
		"Catalog_БанковскиеСчета":             {"Ref_Key", "Owner", "Owner_Type", "НомерСчета"},
		"Catalog_Валюты":                      {"Ref_Key", "Code"},
		"Document_ПоступлениеНаРасчетныйСчет": {"Ref_Key", "Number", "Date", "СуммаДокумента", "Posted", "СчетОрганизации_Key", "Организация_Key", "Контрагент", "НазначениеПлатежа"},
		"Document_СчетНаОплатуПокупателю":     {"Ref_Key", "Number", "Date", "СуммаДокумента", "Posted", "DeletionMark", "Организация_Key", "ВалютаДокумента_Key", "DataVersion"},
		"Document_ПоступлениеНаРасчетныйСчет_РасшифровкаПлатежа": {"Ref_Key", "LineNumber", "СчетНаОплату_Key", "СуммаПлатежа"},
	}
	var service []map[string]string
	var entities, published strings.Builder
	for name, names := range sets {
		service = append(service, map[string]string{"name": name, "url": name})
		fmt.Fprintf(&entities, `<EntityType Name="%s">`, name)
		for _, field := range names {
			fmt.Fprintf(&entities, `<Property Name="%s" Type="Edm.String"/>`, field)
		}
		entities.WriteString(`</EntityType>`)
		fmt.Fprintf(&published, `<EntitySet Name="%s" EntityType="StandardODATA.%s"/>`, name, name)
	}
	metadata := `<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx"><edmx:DataServices><Schema xmlns="http://schemas.microsoft.com/ado/2009/11/edm" Namespace="StandardODATA">` + entities.String() + `<EntityContainer Name="Default">` + published.String() + `</EntityContainer></Schema></edmx:DataServices></edmx:Edmx>`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		user, pass, ok := r.BasicAuth()
		if !ok || user != "reader" || pass != "secret" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(r.URL.Path, "/$metadata") {
			_, _ = w.Write([]byte(metadata))
			return
		}
		for name := range sets {
			if strings.HasSuffix(r.URL.Path, "/"+name) {
				var rows any = []any{}
				switch name {
				case "Catalog_Организации":
					rows = []any{map[string]string{"Ref_Key": "org-1", "ИНН": "7701234567"}}
				case "Catalog_БанковскиеСчета":
					rows = []any{map[string]string{"Ref_Key": "account-1", "Owner": "org-1", "Owner_Type": "StandardODATA.Catalog_Организации", "НомерСчета": "40802810999900003157"}, map[string]string{"Ref_Key": "foreign", "Owner": "org-2", "Owner_Type": "StandardODATA.Catalog_Организации", "НомерСчета": "40802810900000003155"}}
				case "Catalog_Валюты":
					rows = []any{map[string]string{"Ref_Key": "rub-1", "Code": "643"}}
				}
				_ = json.NewEncoder(w).Encode(map[string]any{"value": rows})
				return
			}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"value": service})
	}))
	defer srv.Close()
	client := onecodata.Client{Username: "reader", Password: "secret"}
	root := srv.URL + "/odata/standard.odata/"
	config, plan, err := client.SuggestAccounting(context.Background(), root, "company", "7701234567", "40802810999900003157")
	if err != nil {
		t.Fatal(err)
	}
	if config.Validate() != nil || len(config.AccountMap) != 1 || config.AccountMap["account-1"] != "40802810999900003157" || len(config.Collections) != 1 {
		t.Fatalf("fact mapping: %+v", config)
	}
	if plan == nil || plan.Validate() != nil || len(plan.Invoices) != 1 || len(plan.Payments) != 1 || len(plan.RUBCurrencyIDs) != 1 || plan.RUBCurrencyIDs[0] != "rub-1" {
		t.Fatalf("plan mapping: %+v", plan)
	}
	if _, _, err = client.SuggestAccounting(context.Background(), root, "company", "7701234567", "40802810900000003155"); err == nil {
		t.Fatal("foreign bank account must not be accepted")
	}
}
