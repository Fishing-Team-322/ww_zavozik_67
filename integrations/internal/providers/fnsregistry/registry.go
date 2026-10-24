// Package fnsregistry imports user-supplied official EGRUL/EGRIP files. It does
// not retrieve registry files or claim to validate a digital signature.
package fnsregistry

import (
	"archive/zip"
	"context"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"path"
	"strconv"
	"strings"
	"time"

	"golang.org/x/text/encoding/charmap"
)

const MaxUploadBytes = 128 << 20

type Record struct {
	INN                string   `json:"inn"`
	OGRN               string   `json:"ogrn"`
	EntityType         string   `json:"entity_type"`
	Name               string   `json:"name"`
	RegistrationStatus string   `json:"registration_status"`
	ActualAt           string   `json:"actual_at"`
	ExtractedAt        string   `json:"extracted_at,omitempty"`
	RetrievedAt        string   `json:"retrieved_at"`
	Source             string   `json:"source"`
	SourceFormat       string   `json:"source_format"`
	SignatureStatus    string   `json:"signature_status"`
	Address            string   `json:"address,omitempty"`
	OKVED              []string `json:"okved,omitempty"`
	Director           string   `json:"director,omitempty"`
	Version            int64    `json:"version,omitempty"`
}

type xmlParty struct {
	INN        string `xml:"ИНН,attr"`
	INNFL      string `xml:"ИННФЛ,attr"`
	OGRN       string `xml:"ОГРН,attr"`
	OGRNIP     string `xml:"ОГРНИП,attr"`
	NameLegacy string `xml:"ПолнНаимОПФ,attr"`
	Date       string `xml:"ДатаВып,attr"`
	Name       struct {
		Full string `xml:"НаимЮЛПолн,attr"`
	} `xml:"СвНаимЮЛ"`
	Person struct {
		FIO struct {
			Surname    string `xml:"Фамилия,attr"`
			Given      string `xml:"Имя,attr"`
			Patronymic string `xml:"Отчество,attr"`
		} `xml:"ФИОРус"`
	} `xml:"СвФЛ"`
	ClosedLegal *struct{} `xml:"СвПрекрЮЛ"`
	ClosedIP    *struct{} `xml:"СвПрекращ"`
	Statuses    []struct {
		Status struct {
			LegalName string `xml:"НаимСтатусЮЛ,attr"`
			IPName    string `xml:"НаимСтатус,attr"`
		} `xml:"СвСтатус"`
	} `xml:"СвСтатус"`
	Address struct {
		GR struct {
			Text string `xml:"АдресРФ,attr"`
		} `xml:"АдресРФ"`
	} `xml:"СвАдресЮЛ"`
	OKVED struct {
		Main struct {
			Code string `xml:"КодОКВЭД,attr"`
		} `xml:"СвОКВЭДОсн"`
		Extra []struct {
			Code string `xml:"КодОКВЭД,attr"`
		} `xml:"СвОКВЭДДоп"`
	} `xml:"СвОКВЭД"`
}

type xmlDocument struct {
	Legal *xmlParty `xml:"СвЮЛ"`
	IP    *xmlParty `xml:"СвИП"`
}

func validINN(s string) bool {
	if len(s) != 10 && len(s) != 12 {
		return false
	}
	if strings.Trim(s, "0") == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	check := func(weights []int) int {
		sum := 0
		for i, w := range weights {
			sum += int(s[i]-'0') * w
		}
		return sum % 11 % 10
	}
	if len(s) == 10 {
		return check([]int{2, 4, 10, 3, 5, 9, 4, 6, 8}) == int(s[9]-'0')
	}
	return check([]int{7, 2, 4, 10, 3, 5, 9, 4, 6, 8}) == int(s[10]-'0') && check([]int{3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8}) == int(s[11]-'0')
}

func ValidIdentifier(s string) bool {
	if validINN(s) {
		return true
	}
	if len(s) != 13 && len(s) != 15 {
		return false
	}
	if strings.Trim(s, "0") == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	n, err := strconv.ParseInt(s[:len(s)-1], 10, 64)
	if err != nil {
		return false
	}
	divisor := int64(11)
	if len(s) == 15 {
		divisor = 13
	}
	return int(n%divisor%10) == int(s[len(s)-1]-'0')
}

func ParseXML(ctx context.Context, source io.Reader, received time.Time, emit func(Record) error) (int, error) {
	dec := xml.NewDecoder(io.LimitReader(source, 32<<20+1))
	dec.CharsetReader = func(label string, in io.Reader) (io.Reader, error) {
		if strings.EqualFold(label, "windows-1251") || strings.EqualFold(label, "cp1251") {
			return charmap.Windows1251.NewDecoder().Reader(in), nil
		}
		return nil, fmt.Errorf("unsupported XML encoding %s", label)
	}
	var start xml.StartElement
	ok := false
	for !ok {
		root, err := dec.Token()
		if err != nil {
			return 0, fmt.Errorf("read XML root: %w", err)
		}
		start, ok = root.(xml.StartElement)
	}
	if start.Name.Local != "EGRUL" && start.Name.Local != "EGRIP" && start.Name.Local != "Файл" {
		return 0, errors.New("expected EGRUL, EGRIP or FNS Файл root")
	}
	legal := start.Name.Local == "EGRUL"
	fileRoot := start.Name.Local == "Файл"
	rootDate := ""
	for _, a := range start.Attr {
		if a.Name.Local == "ДатаВыг" || a.Name.Local == "ДатаДок" {
			rootDate = a.Value
		}
	}
	if !fileRoot {
		if _, err := time.Parse("2006-01-02", rootDate); err != nil {
			return 0, errors.New("invalid EGRUL/EGRIP export date")
		}
	}
	count := 0
	for {
		if err := ctx.Err(); err != nil {
			return count, err
		}
		tok, err := dec.Token()
		if err == io.EOF {
			return count, errors.New("truncated EGRUL/EGRIP XML")
		}
		if err != nil {
			return count, fmt.Errorf("read XML: %w", err)
		}
		switch t := tok.(type) {
		case xml.EndElement:
			if t.Name.Local == start.Name.Local {
				if count == 0 {
					return count, errors.New("empty EGRUL/EGRIP file")
				}
				return count, nil
			}
		case xml.StartElement:
			var p xmlParty
			if fileRoot {
				if t.Name.Local == "ИдОтпр" {
					if err := dec.Skip(); err != nil {
						return count, err
					}
					continue
				}
				if t.Name.Local != "Документ" {
					return count, errors.New("unexpected FNS file element")
				}
				var doc xmlDocument
				if err := dec.DecodeElement(&doc, &t); err != nil {
					return count, fmt.Errorf("decode registry document: %w", err)
				}
				if (doc.Legal == nil) == (doc.IP == nil) {
					return count, errors.New("document must contain one СвЮЛ or СвИП")
				}
				if doc.Legal != nil {
					legal = true
					p = *doc.Legal
				} else {
					legal = false
					p = *doc.IP
				}
			} else {
				want := "СвИП"
				if legal {
					want = "СвЮЛ"
				}
				if t.Name.Local != want {
					return count, errors.New("unexpected EGRUL/EGRIP element")
				}
				if err := dec.DecodeElement(&p, &t); err != nil {
					return count, fmt.Errorf("decode registry record: %w", err)
				}
			}
			r := Record{Source: "FNS_EGRIP", SourceFormat: "XML", EntityType: "INDIVIDUAL", SignatureStatus: "NOT_VERIFIED", RetrievedAt: received.UTC().Format(time.RFC3339), ActualAt: p.Date, ExtractedAt: rootDate, RegistrationStatus: "UNKNOWN"}
			if legal {
				r.Source = "FNS_EGRUL"
				r.EntityType = "LEGAL_ENTITY"
				r.INN = p.INN
				r.OGRN = p.OGRN
				r.Name = p.Name.Full
				if r.Name == "" {
					r.Name = p.NameLegacy
				}
			} else {
				r.INN = p.INNFL
				r.OGRN = p.OGRNIP
				r.Name = strings.TrimSpace(strings.Join([]string{p.Person.FIO.Surname, p.Person.FIO.Given, p.Person.FIO.Patronymic}, " "))
			}
			if p.ClosedLegal != nil || p.ClosedIP != nil {
				r.RegistrationStatus = "TERMINATED"
			} else {
				statusName := ""
				if len(p.Statuses) > 0 {
					statusName = p.Statuses[len(p.Statuses)-1].Status.LegalName
					if !legal {
						statusName = p.Statuses[len(p.Statuses)-1].Status.IPName
					}
				}
				if strings.HasPrefix(strings.ToLower(statusName), "действующ") {
					r.RegistrationStatus = "ACTIVE"
				}
			}
			if p.OKVED.Main.Code != "" {
				r.OKVED = append(r.OKVED, p.OKVED.Main.Code)
			}
			for _, item := range p.OKVED.Extra {
				if item.Code != "" && len(r.OKVED) < 100 {
					r.OKVED = append(r.OKVED, item.Code)
				}
			}
			if r.ActualAt == "" {
				r.ActualAt = rootDate
			}
			if _, err := time.Parse("2006-01-02", r.ActualAt); err != nil || !validINN(r.INN) || r.Name == "" || !ValidIdentifier(r.OGRN) || (legal && len(r.OGRN) != 13) || (!legal && len(r.OGRN) != 15) {
				return count, errors.New("invalid registry identity or date")
			}
			if emit != nil {
				if err := emit(r); err != nil {
					return count, err
				}
			}
			count++
			if count > 100000 {
				return count, errors.New("too many registry records")
			}
		}
	}
}

// ParseZIP rejects excessive expansion before parsing and bounds each stream.
func ParseZIP(ctx context.Context, source io.ReaderAt, size int64, received time.Time, emit func(Record) error) (int, error) {
	if size <= 0 || size > MaxUploadBytes {
		return 0, errors.New("registry ZIP exceeds size limit")
	}
	z, err := zip.NewReader(source, size)
	if err != nil {
		return 0, err
	}
	if len(z.File) == 0 || len(z.File) > 200 {
		return 0, errors.New("invalid registry ZIP entry count")
	}
	var total uint64
	for _, f := range z.File {
		total += f.UncompressedSize64
		if path.Base(f.Name) != f.Name || strings.Contains(f.Name, "\\") || !strings.HasSuffix(strings.ToLower(f.Name), ".xml") || f.UncompressedSize64 > 32<<20 || total > 512<<20 || f.CompressedSize64 == 0 || f.UncompressedSize64/f.CompressedSize64 > 300 {
			return 0, errors.New("invalid registry ZIP entry")
		}
	}
	count := 0
	for _, f := range z.File {
		rd, e := f.Open()
		if e != nil {
			return count, e
		}
		n, e := ParseXML(ctx, io.LimitReader(rd, int64(f.UncompressedSize64)+1), received, emit)
		closeErr := rd.Close()
		count += n
		if e != nil {
			return count, e
		}
		if closeErr != nil {
			return count, closeErr
		}
	}
	return count, nil
}
