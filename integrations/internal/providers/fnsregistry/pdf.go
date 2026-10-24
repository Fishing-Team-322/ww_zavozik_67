package fnsregistry

import (
	"errors"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/ledongthuc/pdf"
)

var (
	innPDF             = regexp.MustCompile(`(?m)(?:^|\s)ИНН\s*[:№]?\s*([0-9]{10}|[0-9]{12})\b`)
	ogrnPDF            = regexp.MustCompile(`(?m)(?:^|\s)ОГРН(ИП)?\s*[:№]?\s*([0-9]{13}|[0-9]{15})\b`)
	datePDF            = regexp.MustCompile(`\b([0-3]?[0-9])[. ]([01]?[0-9])[. ](20[0-9]{2})\b`)
	namePDF            = regexp.MustCompile(`(?mi)(?:Полное наименование юридического лица|Фамилия, имя, отчество индивидуального предпринимателя)[^\n]*\n\s*([^\n]{3,300})`)
	legalHeaderNamePDF = regexp.MustCompile(`(?mi)Настоящая выписка содержит сведения о юридическом лице\s*\n\s*([^\n]{3,300})`)
	spacedINNPDF       = regexp.MustCompile(`(?m)(?:^|\s)ИНН\s*[:№]?\s*((?:[0-9]\s*){10,12})`)
	spacedOGRNPDF      = regexp.MustCompile(`(?m)(?:^|\s)ОГРН(ИП)?\s*[:№]?\s*((?:[0-9]\s*){13,15})`)
	digitsPDF          = regexp.MustCompile(`[0-9]`)
)

// ParsePDF reads the PDF text layer. Scanned documents are rejected with a
// specific error so they can be handled separately instead of guessing via OCR.
func ParsePDF(reader io.ReaderAt, size int64, received time.Time) (rec Record, err error) {
	defer func() {
		if p := recover(); p != nil {
			rec = Record{}
			err = errors.New("invalid PDF structure")
		}
	}()
	if size <= 0 || size > 32<<20 {
		return rec, errors.New("PDF exceeds size limit")
	}
	r, err := pdf.NewReader(reader, size)
	if err != nil {
		return rec, fmt.Errorf("open PDF: %w", err)
	}
	if r.NumPage() < 1 || r.NumPage() > 100 {
		return rec, errors.New("invalid PDF page count")
	}
	var text strings.Builder
	for i := 1; i <= r.NumPage(); i++ {
		page := r.Page(i)
		if page.V.IsNull() {
			return rec, errors.New("invalid PDF page")
		}
		s, e := page.GetPlainText(nil)
		if e != nil {
			return rec, fmt.Errorf("read PDF text: %w", e)
		}
		text.WriteString(s)
		text.WriteByte('\n')
		if text.Len() > 2<<20 {
			return rec, errors.New("PDF text exceeds limit")
		}
	}
	s := strings.ReplaceAll(text.String(), "\r", "\n")
	if strings.TrimSpace(s) == "" {
		return rec, errors.New("PDF has no text layer; OCR is required")
	}
	legal := strings.Contains(strings.ToUpper(s), "ЕГРЮЛ") || strings.Contains(strings.ToUpper(s), "ЕДИНОГО ГОСУДАРСТВЕННОГО РЕЕСТРА ЮРИДИЧЕСКИХ ЛИЦ")
	ip := strings.Contains(strings.ToUpper(s), "ЕГРИП") || strings.Contains(strings.ToUpper(s), "ЕДИНОГО ГОСУДАРСТВЕННОГО РЕЕСТРА ИНДИВИДУАЛЬНЫХ ПРЕДПРИНИМАТЕЛЕЙ")
	if legal == ip {
		return rec, errors.New("unknown PDF registry type")
	}
	header := s
	if len(header) > 1500 {
		header = header[:1500]
	}
	name := namePDF.FindStringSubmatch(s)
	innValue, ogrnValue := pdfIdentifiers(header, legal)
	if legal {
		if headerName := legalHeaderNamePDF.FindStringSubmatch(s); len(headerName) > 1 {
			name = headerName
		}
	}
	date := datePDF.FindStringSubmatch(header)
	if innValue == "" || ogrnValue == "" || len(name) == 0 || len(date) == 0 {
		return rec, errors.New("PDF is missing required registry fields")
	}
	day, _ := strconv.Atoi(date[1])
	month, _ := strconv.Atoi(date[2])
	actual, err := time.Parse("02.01.2006", fmt.Sprintf("%02d.%02d.%s", day, month, date[3]))
	if err != nil {
		return rec, errors.New("invalid PDF extract date")
	}
	rec = Record{INN: innValue, OGRN: ogrnValue, Name: strings.TrimSpace(name[1]), ActualAt: actual.Format("2006-01-02"), ExtractedAt: actual.Format("2006-01-02"), RetrievedAt: received.UTC().Format(time.RFC3339), RegistrationStatus: "UNKNOWN", SourceFormat: "PDF", SignatureStatus: "NOT_VERIFIED"}
	if legal {
		rec.Source = "FNS_EGRUL"
		rec.EntityType = "LEGAL_ENTITY"
	} else {
		rec.Source = "FNS_EGRIP"
		rec.EntityType = "INDIVIDUAL"
	}
	if !validINN(rec.INN) || !ValidIdentifier(rec.OGRN) || (legal && (len(rec.INN) != 10 || len(rec.OGRN) != 13)) || (!legal && (len(rec.INN) != 12 || len(rec.OGRN) != 15)) {
		return Record{}, errors.New("invalid PDF registry identifiers")
	}
	if strings.Contains(strings.ToLower(s), "деятельность прекращена") || strings.Contains(strings.ToLower(s), "юридическое лицо ликвидировано") {
		rec.RegistrationStatus = "TERMINATED"
	}
	return rec, nil
}

func pdfIdentifiers(header string, legal bool) (inn, ogrn string) {
	innLength, ogrnLength := 12, 15
	if legal {
		innLength, ogrnLength = 10, 13
	}
	for _, match := range spacedINNPDF.FindAllStringSubmatch(header, -1) {
		value := strings.Join(digitsPDF.FindAllString(match[1], -1), "")
		if len(value) == innLength && validINN(value) {
			inn = value
			break
		}
	}
	for _, match := range spacedOGRNPDF.FindAllStringSubmatch(header, -1) {
		value := strings.Join(digitsPDF.FindAllString(match[2], -1), "")
		if len(value) == ogrnLength && ValidIdentifier(value) {
			ogrn = value
			break
		}
	}
	if inn == "" {
		for _, match := range innPDF.FindAllStringSubmatch(header, -1) {
			if len(match[1]) == innLength && validINN(match[1]) {
				inn = match[1]
				break
			}
		}
	}
	if ogrn == "" {
		for _, match := range ogrnPDF.FindAllStringSubmatch(header, -1) {
			if len(match[2]) == ogrnLength && ValidIdentifier(match[2]) {
				ogrn = match[2]
				break
			}
		}
	}
	return inn, ogrn
}
