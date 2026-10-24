package onecodata

import (
	"context"
	"encoding/json"
	"encoding/xml"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const maxMetadataBytes = 8 << 20

// Discovery describes published collections and field names, without returning records.
type Discovery struct {
	Collections []CollectionInfo `json:"collections"`
}

type CollectionInfo struct {
	Name   string      `json:"name"`
	Fields []FieldInfo `json:"fields"`
}

type FieldInfo struct {
	Name string `json:"name" xml:"Name,attr"`
	Type string `json:"type" xml:"Type,attr"`
}

type serviceDocument struct {
	Value []struct {
		Name string `json:"name"`
		URL  string `json:"url"`
	} `json:"value"`
}

type metadataDocument struct {
	DataServices struct {
		Schemas []struct {
			Namespace   string `xml:"Namespace,attr"`
			EntityTypes []struct {
				Name       string      `xml:"Name,attr"`
				Properties []FieldInfo `xml:"Property"`
			} `xml:"EntityType"`
			Containers []struct {
				Sets []struct {
					Name       string `xml:"Name,attr"`
					EntityType string `xml:"EntityType,attr"`
				} `xml:"EntitySet"`
			} `xml:"EntityContainer"`
		} `xml:"Schema"`
	} `xml:"DataServices"`
}

// Inspect reads the OData service document and metadata to discover a 1C mapping.
// It never returns record values or upstream error bodies.
func (c Client) Inspect(ctx context.Context, baseURL string) (Discovery, error) {
	result := Discovery{Collections: []CollectionInfo{}}
	u, err := url.Parse(baseURL)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || !strings.HasSuffix(u.Path, "/") ||
		(u.Scheme != "https" && (u.Scheme != "http" || !isLoopback(u.Hostname()))) ||
		(c.Username == "" && c.Password != "") {
		return result, ErrConfig
	}
	if _, ok := ctx.Deadline(); !ok {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, 30*time.Second)
		defer cancel()
	}
	httpClient := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if c.HTTP != nil {
		httpClient.Transport = c.HTTP.Transport
	}
	root, err := c.inspectGet(ctx, httpClient, baseURL, maxPageBytes)
	if err != nil {
		return result, err
	}
	var service serviceDocument
	if json.Unmarshal(root, &service) != nil || service.Value == nil || len(service.Value) > 512 {
		return result, ErrUpstream
	}
	meta, err := c.inspectGet(ctx, httpClient, baseURL+"$metadata", maxMetadataBytes)
	if err != nil {
		return result, err
	}
	var doc metadataDocument
	if xml.Unmarshal(meta, &doc) != nil {
		return result, ErrUpstream
	}
	types := map[string][]FieldInfo{}
	sets := map[string]string{}
	for _, schema := range doc.DataServices.Schemas {
		for _, entity := range schema.EntityTypes {
			types[schema.Namespace+"."+entity.Name] = entity.Properties
		}
		for _, container := range schema.Containers {
			for _, set := range container.Sets {
				sets[set.Name] = set.EntityType
			}
		}
	}
	for _, item := range service.Value {
		if !validEntity(item.Name) || item.URL != item.Name {
			return Discovery{}, ErrUpstream
		}
		fields, ok := types[sets[item.Name]]
		if !ok {
			return Discovery{}, ErrUpstream
		}
		result.Collections = append(result.Collections, CollectionInfo{Name: item.Name, Fields: fields})
	}
	return result, nil
}

func (c Client) inspectGet(ctx context.Context, client *http.Client, address string, limit int64) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, address, nil)
	if err != nil {
		return nil, ErrConfig
	}
	req.Header.Set("Accept", "application/json, application/xml")
	if c.Username != "" {
		req.SetBasicAuth(c.Username, c.Password)
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, ErrUpstream
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
		return nil, ErrAuth
	}
	if resp.StatusCode != http.StatusOK {
		return nil, ErrUpstream
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, limit+1))
	if err != nil {
		return nil, ErrUpstream
	}
	if int64(len(data)) > limit {
		return nil, ErrLimit
	}
	return data, nil
}
