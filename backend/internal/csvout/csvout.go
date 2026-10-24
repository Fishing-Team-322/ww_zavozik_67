// Package csvout — CSV-выгрузки cmd/export и cmd/backtest с проверкой ошибок.
// encoding/csv буферизует записи, поэтому первая ошибка файловой системы может
// всплыть только на Flush: успех нельзя сообщать до Close.
package csvout

import (
	"encoding/csv"
	"os"
)

// File пишет CSV-записи в открытый файл и запоминает первую ошибку.
type File struct {
	f   *os.File
	w   *csv.Writer
	err error
}

func New(f *os.File) *File {
	return &File{f: f, w: csv.NewWriter(f)}
}

// Write пишет запись; после первой ошибки дальнейшие записи игнорируются,
// чтобы не затирать исходную причину.
func (f *File) Write(record []string) {
	if f.err == nil {
		f.err = f.w.Write(record)
	}
}

// Close сбрасывает буфер и закрывает файл, возвращая первую ошибку записи,
// flush или close. Вызывается ровно один раз и до сообщения об успехе.
func (f *File) Close() error {
	f.w.Flush()
	if f.err == nil {
		f.err = f.w.Error()
	}
	if err := f.f.Close(); f.err == nil {
		f.err = err
	}
	return f.err
}
