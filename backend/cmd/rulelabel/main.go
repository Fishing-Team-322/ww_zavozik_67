// Command rulelabel размечает операции правилами categorize.DefaultRules —
// ровно тем кодом, что в проде. Нужен ML: слабые метки для обучения
// классификатора и сравнение «правила против модели» на любом наборе.
//
//	go run ./cmd/rulelabel -in ../cashflow_dataset_participants/all_operations.csv -out ../ml/data/rule_labels.csv
//
// Вход — CSV с разделителем «;» (UTF-8, BOM допускается) и заголовком,
// в котором есть колонки direction, counterparty_name, payment_purpose;
// идентификатор строки — колонка operation_id или id (иначе номер строки).
// direction: «Поступление»/«Списание» или in/out.
// Выход — CSV «;»: id;category;confidence. Категория «other» — правила
// ничего не нашли (как Chain с одним звеном).
package main

import (
	"context"
	"encoding/csv"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

func main() {
	inPath := flag.String("in", "", "входной CSV")
	outPath := flag.String("out", "", "куда писать (пусто — stdout)")
	flag.Parse()
	if *inPath == "" {
		fail(errors.New("-in обязателен"))
	}
	in, err := os.Open(*inPath)
	if err != nil {
		fail(err)
	}
	defer in.Close()
	var out io.Writer = os.Stdout
	if *outPath != "" {
		f, err := os.Create(*outPath)
		if err != nil {
			fail(err)
		}
		defer f.Close()
		out = f
	}
	if err := run(context.Background(), in, out); err != nil {
		fail(err)
	}
}

const bom = "\xef\xbb\xbf"

func run(ctx context.Context, in io.Reader, out io.Writer) error {
	r := csv.NewReader(in)
	r.Comma = ';'
	r.FieldsPerRecord = -1
	head, err := r.Read()
	if err != nil {
		return fmt.Errorf("header: %w", err)
	}
	col := map[string]int{}
	for i, h := range head {
		col[strings.TrimSpace(strings.TrimPrefix(h, bom))] = i
	}
	for _, need := range []string{"direction", "counterparty_name", "payment_purpose"} {
		if _, ok := col[need]; !ok {
			return fmt.Errorf("нет колонки %q", need)
		}
	}
	idCol, hasID := col["operation_id"]
	if !hasID {
		idCol, hasID = col["id"]
	}

	var ids []string
	var ops []domain.Operation
	for line := 2; ; line++ {
		rec, err := r.Read()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return fmt.Errorf("line %d: %w", line, err)
		}
		get := func(name string) string {
			if i, ok := col[name]; ok && i < len(rec) {
				return rec[i]
			}
			return ""
		}
		id := strconv.Itoa(line - 1)
		if hasID && idCol < len(rec) {
			id = rec[idCol]
		}
		var dir domain.Direction
		switch strings.ToLower(strings.TrimSpace(get("direction"))) {
		case "поступление", "in":
			dir = domain.In
		case "списание", "out":
			dir = domain.Out
		default:
			return fmt.Errorf("line %d: direction %q", line, get("direction"))
		}
		ids = append(ids, id)
		ops = append(ops, domain.Operation{
			Direction:        dir,
			CounterpartyName: domain.Name(get("counterparty_name")),
			Purpose:          domain.Purpose(get("payment_purpose")),
		})
	}

	chain := categorize.Chain{Steps: []categorize.Categorizer{categorize.DefaultRules}, Threshold: 0.5}
	res, err := chain.Categorize(ctx, ops)
	if err != nil {
		return err
	}
	w := csv.NewWriter(out)
	w.Comma = ';'
	_ = w.Write([]string{"id", "category", "confidence"})
	for i, rr := range res {
		_ = w.Write([]string{ids[i], string(rr.Category), strconv.FormatFloat(rr.Confidence, 'f', 2, 64)})
	}
	w.Flush()
	return w.Error()
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, "rulelabel:", err)
	os.Exit(1)
}
