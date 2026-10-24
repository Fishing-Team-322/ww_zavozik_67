package fns

import (
	"context"
	"errors"
	"html"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

var (
	archiveLink = regexp.MustCompile(`https://file\.nalog\.ru/opendata/7707329152-debtam/data-([0-9]{8})-structure-([0-9]{8})\.zip`)
	asOfText    = regexp.MustCompile(`Данные\s+на\s+([0-3][0-9]\.[01][0-9]\.20[0-9]{2})`)
	htmlTag     = regexp.MustCompile(`<[^>]+>`)
)

type Publication struct {
	Version     string `json:"version"`
	URL         string `json:"url"`
	PublishedAt string `json:"published_at"`
	DatasetAsOf string `json:"dataset_as_of"`
}

// DiscoverDebt follows the public dataset page. It does not use a hidden API.
func DiscoverDebt(ctx context.Context, client *http.Client, pageURL string) (Publication, error) {
	var p Publication
	if client == nil {
		client = &http.Client{Timeout: 20 * time.Second}
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, pageURL, nil)
	if err != nil {
		return p, err
	}
	request.Header.Set("User-Agent", "ZavozikIntegrationHub/1.0 (FNS public dataset update check)")
	resp, err := client.Do(request)
	if err != nil {
		return p, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return p, errors.New("FNS dataset page unavailable")
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20+1))
	if err != nil {
		return p, err
	}
	if len(b) > 2<<20 {
		return p, errors.New("FNS dataset page too large")
	}
	s := html.UnescapeString(string(b))
	m := archiveLink.FindStringSubmatch(s)
	if len(m) == 0 {
		return p, errors.New("FNS dataset link not found")
	}
	if u, err := url.Parse(m[0]); err != nil || u.Host != "file.nalog.ru" || u.Scheme != "https" {
		return p, errors.New("invalid FNS dataset link")
	}
	pageText := html.UnescapeString(htmlTag.ReplaceAllString(s, " "))
	asOf := asOfText.FindStringSubmatch(pageText)
	if len(asOf) == 0 {
		return p, errors.New("FNS dataset as-of date not found")
	}
	d, err := time.Parse("02.01.2006", asOf[1])
	if err != nil {
		return p, err
	}
	pub, err := time.Parse("20060102", m[1])
	if err != nil {
		return p, err
	}
	p = Publication{Version: m[1] + "-" + m[2], URL: strings.TrimSpace(m[0]), PublishedAt: pub.Format("2006-01-02"), DatasetAsOf: d.Format("2006-01-02")}
	return p, nil
}
