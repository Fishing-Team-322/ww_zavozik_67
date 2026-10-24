// mlimpact measures the effect of opting into Hybrid on development operations.
// It uses the real Go categorizer and Python RPC, never retrains or changes data.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	categorizev1 "github.com/Fishing-Team-322/ww_zavozik_67/backend/gen/categorize/v1"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/dataset"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

type impact struct {
	Operations       int            `json:"operations"`
	Changed          int            `json:"category_changed"`
	InternalChanged  int            `json:"internal_membership_changed"`
	ChangedTurnover  float64        `json:"changed_category_turnover"`
	InternalTurnover float64        `json:"changed_internal_membership_turnover"`
	BusinessNetDelta float64        `json:"business_net_delta"`
	Transitions      map[string]int `json:"transitions"`
}

func compare(ops []domain.Operation, labels []categorize.Result) (impact, error) {
	if len(ops) != len(labels) {
		return impact{}, fmt.Errorf("label count mismatch")
	}
	r := impact{Operations: len(ops), Transitions: map[string]int{}}
	for i, op := range ops {
		next := labels[i].Category
		if op.Category != next {
			r.Changed++
			r.ChangedTurnover += op.Amount.Float()
			r.Transitions[string(op.Category)+" -> "+string(next)]++
		}
		if op.Category.IsInternal() != next.IsInternal() {
			r.InternalChanged++
			r.InternalTurnover += op.Amount.Float()
			if next.IsInternal() {
				r.BusinessNetDelta -= op.Signed().Float()
			} else {
				r.BusinessNetDelta += op.Signed().Float()
			}
		}
	}
	return r, nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	data := flag.String("data", "../cashflow_dataset_participants/statements", "statement directory")
	split := flag.String("split", "../ml/eval/split_v2.json", "development company/time exclusions")
	addr := flag.String("ml", "", "explicit test gRPC address (required)")
	out := flag.String("out", "", "new output JSON; existing files are never replaced")
	flag.Parse()
	if *addr == "" || *out == "" {
		return fmt.Errorf("-ml and -out are required")
	}
	if _, err := os.Stat(*out); err == nil {
		return fmt.Errorf("output already exists: %s", *out)
	} else if !os.IsNotExist(err) {
		return err
	}
	raw, err := os.ReadFile(*split)
	if err != nil {
		return err
	}
	var spec struct {
		AuditStart     string   `json:"audit_start"`
		AuditCompanies []string `json:"audit_companies"`
	}
	if err := json.Unmarshal(raw, &spec); err != nil {
		return err
	}
	boundary, err := time.Parse(domain.DateLayout, spec.AuditStart)
	if err != nil {
		return err
	}
	excluded := map[string]bool{}
	for _, id := range spec.AuditCompanies {
		excluded[id] = true
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	ml, err := categorize.DialMLCategorizer(*addr)
	if err != nil {
		return err
	}
	defer ml.Close()
	ml.FailOpen = false // Never disguise a service failure as zero category drift.
	version, err := ml.Client.Classify(ctx, &categorizev1.ClassifyRequest{})
	if err != nil {
		return err
	}
	files, err := dataset.Files(*data, nil)
	if err != nil {
		return err
	}
	if len(files) == 0 {
		return fmt.Errorf("no statement files")
	}
	base := categorize.Chain{Steps: []categorize.Categorizer{categorize.DefaultRules}, Threshold: .5}
	hybrid := categorize.Hybrid{ML: ml, MinMLConfidence: .8}
	rows := map[string]impact{}
	hashes := map[string]string{}
	started := time.Now()
	for _, file := range files {
		id := strings.TrimSuffix(filepath.Base(file), ".csv")
		if excluded[id] {
			continue
		}
		company, err := dataset.Load(ctx, file, base)
		if err != nil {
			return err
		}
		ops := make([]domain.Operation, 0, len(company.Ops))
		for _, op := range company.Ops {
			if op.Date.Before(boundary) {
				ops = append(ops, op)
			}
		}
		if len(ops) == 0 {
			continue
		}
		labels, err := hybrid.Categorize(ctx, ops)
		if err != nil {
			return err
		}
		rows[id], err = compare(ops, labels)
		if err != nil {
			return err
		}
		contents, err := os.ReadFile(file)
		if err != nil {
			return err
		}
		digest := sha256.Sum256(contents)
		hashes[id] = hex.EncodeToString(digest[:])
		if len(rows)%10 == 0 {
			fmt.Fprintf(os.Stderr, "%d companies, elapsed %s\n", len(rows), time.Since(started).Round(time.Second))
		}
	}
	endVersion, err := ml.Client.Classify(ctx, &categorizev1.ClassifyRequest{})
	if err != nil {
		return err
	}
	if version.ModelVersion != endVersion.ModelVersion {
		return fmt.Errorf("model changed during diagnostic")
	}
	splitHash := sha256.Sum256(raw)
	report := map[string]any{"protocol": "development_input_drift_only", "before_exclusive": spec.AuditStart,
		"excluded_companies": spec.AuditCompanies, "model_version": version.ModelVersion, "min_ml_confidence": .8,
		"companies": rows, "source_statement_sha256": hashes, "split_sha256": hex.EncodeToString(splitHash[:]),
		"seconds": time.Since(started).Seconds(), "limitation": "Category differences are not correctness labels. Classifier was fitted on this synthetic case. No forecast fit/audit, no automatic data or model replacement."}
	payload, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		return err
	}
	file, err := os.OpenFile(*out, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
	if err != nil {
		return err
	}
	_, writeErr := file.Write(append(payload, '\n'))
	closeErr := file.Close()
	if writeErr != nil {
		return writeErr
	}
	return closeErr
}
