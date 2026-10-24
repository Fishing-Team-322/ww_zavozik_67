package fns

import (
	"archive/zip"
	"context"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/money"
)

const DatasetURL = "https://www.nalog.gov.ru/opendata/7707329152-debtam/"

// Debt is a dated public-dataset observation, never a live tax-account balance.
type Debt struct {
	INN            string `json:"inn"`
	DocumentID     string `json:"document_id"`
	TaxName        string `json:"tax_name"`
	AmountKopecks  int64  `json:"amount_kopecks"`
	DatasetAsOf    string `json:"dataset_as_of"`
	PublishedAt    string `json:"published_at"`
	RetrievedAt    string `json:"retrieved_at"`
	SourceURL      string `json:"source_url"`
	DataMode       string `json:"data_mode"`
	Interpretation string `json:"interpretation"`
}

type Summary struct {
	Files     int `json:"files"`
	Documents int `json:"documents"`
	Matches   int `json:"matches"`
}

type document struct {
	ID    string `xml:"ИдДок,attr"`
	Date  string `xml:"ДатаДок,attr"`
	AsOf  string `xml:"ДатаСост,attr"`
	Party struct {
		INN string `xml:"ИННЮЛ,attr"`
	} `xml:"СведНП"`
	Items []struct {
		Tax    string `xml:"НаимНалог,attr"`
		Amount string `xml:"ОбщСумНедоим,attr"`
	} `xml:"СведНедоим"`
}

// ParseArchive scans the official XML ZIP without extracting it or loading the
// nationwide dataset in memory. An empty result means "not in this snapshot".
// The caller must supply the exact dated download URL and a nonempty INN filter.
func ParseArchive(ctx context.Context, reader io.ReaderAt, size int64, inns map[string]struct{}, sourceURL string, retrievedAt time.Time) ([]Debt, Summary, error) {
	var summary Summary
	if size <= 0 || size > 256<<20 || len(inns) == 0 || len(inns) > 10000 || !strings.HasPrefix(sourceURL, "https://file.nalog.ru/opendata/7707329152-debtam/") {
		return nil, summary, errors.New("invalid FNS archive input")
	}
	for inn := range inns {
		if len(inn) != 10 {
			return nil, summary, errors.New("FNS debt dataset supports 10-digit legal entity INN only")
		}
		for _, c := range inn {
			if c < '0' || c > '9' {
				return nil, summary, errors.New("invalid INN")
			}
		}
	}
	zr, err := zip.NewReader(reader, size)
	if err != nil {
		return nil, summary, fmt.Errorf("open FNS ZIP: %w", err)
	}
	if len(zr.File) == 0 || len(zr.File) > 2000 {
		return nil, summary, errors.New("unexpected FNS ZIP entry count")
	}
	var total uint64
	for _, entry := range zr.File {
		if !strings.HasSuffix(strings.ToLower(entry.Name), ".xml") || strings.ContainsAny(entry.Name, `/\`) || entry.UncompressedSize64 > 16<<20 {
			return nil, summary, errors.New("invalid FNS ZIP entry")
		}
		total += entry.UncompressedSize64
		if total > 2<<30 || entry.CompressedSize64 == 0 || entry.UncompressedSize64/entry.CompressedSize64 > 200 {
			return nil, summary, errors.New("FNS ZIP size limit exceeded")
		}
	}
	results := make([]Debt, 0)
	for _, entry := range zr.File {
		if err := ctx.Err(); err != nil {
			return nil, summary, err
		}
		stream, err := entry.Open()
		if err != nil {
			return nil, summary, fmt.Errorf("open FNS XML: %w", err)
		}
		dec := xml.NewDecoder(io.LimitReader(stream, int64(entry.UncompressedSize64)+1))
		for {
			token, err := dec.Token()
			if err == io.EOF {
				break
			}
			if err != nil {
				stream.Close()
				return nil, summary, fmt.Errorf("parse FNS XML: %w", err)
			}
			start, ok := token.(xml.StartElement)
			if !ok || start.Name.Local != "Документ" {
				continue
			}
			if summary.Documents%1000 == 0 {
				if err := ctx.Err(); err != nil {
					stream.Close()
					return nil, summary, err
				}
			}
			var doc document
			if err := dec.DecodeElement(&doc, &start); err != nil {
				stream.Close()
				return nil, summary, fmt.Errorf("decode FNS document: %w", err)
			}
			summary.Documents++
			if _, wanted := inns[doc.Party.INN]; !wanted {
				continue
			}
			asOf, err := time.Parse("02.01.2006", doc.AsOf)
			if err != nil || doc.ID == "" || len(doc.Items) == 0 {
				stream.Close()
				return nil, summary, errors.New("invalid FNS matched document")
			}
			published, err := time.Parse("02.01.2006", doc.Date)
			if err != nil {
				stream.Close()
				return nil, summary, errors.New("invalid FNS publication date")
			}
			for _, item := range doc.Items {
				amount, err := money.Parse(item.Amount)
				if err != nil || item.Tax == "" {
					stream.Close()
					return nil, summary, errors.New("invalid FNS debt item")
				}
				results = append(results, Debt{INN: doc.Party.INN, DocumentID: doc.ID, TaxName: item.Tax, AmountKopecks: amount, DatasetAsOf: asOf.Format("2006-01-02"), PublishedAt: published.Format("2006-01-02"), RetrievedAt: retrievedAt.UTC().Format(time.RFC3339), SourceURL: sourceURL, DataMode: "import", Interpretation: "published_debt_snapshot_not_current_balance"})
				summary.Matches++
			}
		}
		if err := stream.Close(); err != nil {
			return nil, summary, fmt.Errorf("close FNS XML: %w", err)
		}
		summary.Files++
	}
	return results, summary, nil
}
