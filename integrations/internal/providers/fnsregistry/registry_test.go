package fnsregistry

import (
	"archive/zip"
	"bytes"
	"context"
	"golang.org/x/text/encoding/charmap"
	"os"
	"strings"
	"testing"
	"time"
)

const legalXML = `<?xml version="1.0" encoding="UTF-8"?><EGRUL ДатаВыг="2026-10-24"><СвЮЛ ИНН="9723161623" ОГРН="1234567890127" ДатаВып="2026-10-20"><СвНаимЮЛ НаимЮЛПолн="Тестовая компания"/></СвЮЛ><СвЮЛ ИНН="9723161623" ОГРН="1234567890127" ДатаВып="2026-10-21"><СвНаимЮЛ НаимЮЛПолн="Новая компания"/><СвПрекрЮЛ/></СвЮЛ></EGRUL>`
const ipXML = `<EGRIP ДатаВыг="2026-10-24"><СвИП ИННФЛ="500100732259" ОГРНИП="123456789012343" ДатаВып="2026-10-23"><СвФЛ><ФИОРус Фамилия="Тестов" Имя="Тест" Отчество="Тестович"/></СвФЛ><СвПрекращ/></СвИП></EGRIP>`

func TestRegistryXMLVersionsAndIP(t *testing.T) {
	var got []Record
	emit := func(r Record) error { got = append(got, r); return nil }
	n, e := ParseXML(context.Background(), strings.NewReader(legalXML), time.Now(), emit)
	if e != nil || n != 2 || got[0].Name != "Тестовая компания" || got[1].RegistrationStatus != "TERMINATED" {
		t.Fatalf("legal: %d %+v %v", n, got, e)
	}
	got = nil
	n, e = ParseXML(context.Background(), strings.NewReader(ipXML), time.Now(), emit)
	if e != nil || n != 1 || got[0].EntityType != "INDIVIDUAL" || got[0].Name != "Тестов Тест Тестович" || got[0].RegistrationStatus != "TERMINATED" {
		t.Fatalf("ip: %d %+v %v", n, got, e)
	}
}
func TestRegistryZIPAndInvalidFiles(t *testing.T) {
	var buf bytes.Buffer
	z := zip.NewWriter(&buf)
	for i, s := range []string{legalXML, ipXML} {
		w, e := z.Create([]string{"EGRUL.xml", "EGRIP.xml"}[i])
		if e != nil {
			t.Fatal(e)
		}
		_, _ = w.Write([]byte(s))
	}
	if e := z.Close(); e != nil {
		t.Fatal(e)
	}
	n, e := ParseZIP(context.Background(), bytes.NewReader(buf.Bytes()), int64(buf.Len()), time.Now(), nil)
	if e != nil || n != 3 {
		t.Fatalf("archive: %d %v", n, e)
	}
	if _, e = ParseXML(context.Background(), strings.NewReader(`<EGRUL ДатаВыг="2026-10-24"><СвЮЛ ИНН="9723161624" ОГРН="1234567890127" ДатаВып="2026-10-24"><СвНаимЮЛ НаимЮЛПолн="X"/></СвЮЛ></EGRUL>`), time.Now(), nil); e == nil {
		t.Fatal("invalid INN accepted")
	}
	if _, e = ParseXML(context.Background(), strings.NewReader(legalXML[:len(legalXML)-8]), time.Now(), nil); e == nil {
		t.Fatal("truncated XML accepted")
	}
	if _, e = ParseZIP(context.Background(), bytes.NewReader(buf.Bytes()), MaxUploadBytes+1, time.Now(), nil); e == nil {
		t.Fatal("oversized ZIP accepted")
	}
}

func TestSyntheticTextLayerPDF(t *testing.T) {
	f, e := os.Open("testdata/synthetic_egrul.pdf")
	if e != nil {
		t.Fatal(e)
	}
	defer f.Close()
	stat, e := f.Stat()
	if e != nil {
		t.Fatal(e)
	}
	r, e := ParsePDF(f, stat.Size(), time.Now())
	if e != nil || r.INN != "9723161623" || r.Source != "FNS_EGRUL" || r.SignatureStatus != "NOT_VERIFIED" {
		t.Fatalf("pdf: %+v %v", r, e)
	}
}

func TestWindows1251RegistryAndZIPTraversal(t *testing.T) {
	xmlText := strings.Replace(legalXML, "UTF-8", "windows-1251", 1)
	b, e := charmap.Windows1251.NewEncoder().Bytes([]byte(xmlText))
	if e != nil {
		t.Fatal(e)
	}
	n, e := ParseXML(context.Background(), bytes.NewReader(b), time.Now(), nil)
	if e != nil || n != 2 {
		t.Fatalf("cp1251: %d %v", n, e)
	}
	var buf bytes.Buffer
	z := zip.NewWriter(&buf)
	w, e := z.Create(`..\evil.xml`)
	if e != nil {
		t.Fatal(e)
	}
	_, _ = w.Write(b)
	_ = z.Close()
	if _, e = ParseZIP(context.Background(), bytes.NewReader(buf.Bytes()), int64(buf.Len()), time.Now(), nil); e == nil {
		t.Fatal("traversal accepted")
	}
}

func TestOfficialXSDFileWrapper(t *testing.T) {
	legal := `<?xml version="1.0"?><Файл ВерсФорм="4.08" ДатаДок="2026-10-24"><Документ ИдДок="1"><СвЮЛ ИНН="9723161623" ОГРН="1234567890127" ДатаВып="2026-10-20"><СвНаимЮЛ НаимЮЛПолн="Компания"/><СвСтатус><СвСтатус НаимСтатусЮЛ="Действующее"/></СвСтатус><СвОКВЭД><СвОКВЭДОсн КодОКВЭД="47.11"/></СвОКВЭД></СвЮЛ></Документ><Документ ИдДок="2"><СвЮЛ ИНН="9723161623" ОГРН="1234567890127" ДатаВып="2026-10-21"><СвНаимЮЛ НаимЮЛПолн="Компания новая"/><СвПрекрЮЛ/></СвЮЛ></Документ></Файл>`
	ip := `<?xml version="1.0"?><Файл ВерсФорм="4.07" ДатаДок="2026-10-24"><Документ ИдДок="3"><СвИП ИННФЛ="500100732259" ОГРНИП="123456789012343" ДатаВып="2026-10-23"><СвФЛ><ФИОРус Фамилия="Тестов" Имя="Тест"/></СвФЛ></СвИП></Документ></Файл>`
	var got []Record
	emit := func(r Record) error { got = append(got, r); return nil }
	n, e := ParseXML(context.Background(), strings.NewReader(legal), time.Now(), emit)
	if e != nil || n != 2 || got[0].RegistrationStatus != "ACTIVE" || len(got[0].OKVED) != 1 || got[0].OKVED[0] != "47.11" || got[1].RegistrationStatus != "TERMINATED" {
		t.Fatalf("legal wrapper: %d %+v %v", n, got, e)
	}
	got = nil
	n, e = ParseXML(context.Background(), strings.NewReader(ip), time.Now(), emit)
	if e != nil || n != 1 || got[0].EntityType != "INDIVIDUAL" {
		t.Fatalf("IP wrapper: %d %+v %v", n, got, e)
	}
}
