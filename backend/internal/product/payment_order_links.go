package product

import (
	"context"
	"math"
	"regexp"
	"strings"
)

// Links are derived from current records rather than persisted suppression flags:
// removing/cancelling/editing an invoice must not permanently hide a bank order.
func (s *Service) eventRows(ctx context.Context, uid, cid string) ([]Doc, error) {
	events, err := s.DB.ProductList(ctx, uid, cid, "event")
	if err != nil {
		return nil, err
	}
	return s.linkPaymentOrders(ctx, uid, cid, events)
}

func (s *Service) linkPaymentOrders(ctx context.Context, uid, cid string, events []Doc) ([]Doc, error) {
	needed := false
	for _, event := range events {
		if flag(event, "_payment_order_link") {
			if text(event, "status") == "linked" {
				event["status"] = event["link_original_status"]
			}
			if original, exists := event["_original_link_status"]; exists {
				event["link_status"] = original
			} else {
				delete(event, "link_status")
			}
		}
		delete(event, "linked_event_id")
		delete(event, "linked_sources")
		delete(event, "link_original_status")
		delete(event, "_payment_order_link")
		delete(event, "_original_link_status")
		needed = needed || text(event, "source_kind") == "bank_api" && text(event, "obligation_kind") == "payment_order"
	}
	if !needed {
		return events, nil
	}
	invoices, err := s.DB.ProductList(ctx, uid, cid, "invoice")
	if err != nil {
		return nil, err
	}
	numbers := map[string]string{}
	for _, invoice := range invoices {
		numbers[text(invoice, "id")] = text(invoice, "number")
	}
	candidates := map[string][]Doc{}
	uses := map[string]int{}
	for _, order := range events {
		if text(order, "source_kind") != "bank_api" || text(order, "obligation_kind") != "payment_order" || !in(text(order, "status"), "expected missed received") {
			continue
		}
		explicit := text(order, "related_event_id")
		for _, event := range events {
			if !in(text(event, "source_kind"), "invoice contract onec_odata tax_calendar tax_api manual recurring") || !in(text(event, "status"), "expected missed received") {
				continue
			}
			// A confirmed shared bank receipt remains a strong link when a paid
			// invoice projection is rebuilt with its full rather than residual sum.
			if receipt := text(order, "matched_operation_id"); receipt != "" && receipt == text(event, "matched_operation_id") {
				candidates[text(order, "id")] = append(candidates[text(order, "id")], event)
				uses[text(event, "id")]++
				continue
			}
			if text(order, "direction") != text(event, "direction") || date(order["event_date"]) != date(event["event_date"]) || math.Round(number(order, "amount")*100) != math.Round(number(event, "amount")*100) {
				continue
			}
			if explicit != "" {
				if explicit != text(event, "id") {
					continue
				}
				// A strong reference permits missing party metadata, but not conflicting known parties.
				if (text(order, "counterparty_inn") != "" && text(event, "counterparty_inn") != "" || text(order, "counterparty_name") != "" && text(event, "counterparty_name") != "") && !samePaymentCounterparty(order, event) {
					continue
				}
			} else {
				if !samePaymentCounterparty(order, event) {
					continue
				}
				number := numbers[text(event, "document_id")]
				if number == "" && text(event, "source_kind") == "onec_odata" {
					number = referencedInvoiceNumber(text(event, "title"))
				}
				if number == "" || !orderReferencesInvoice(order, number) {
					continue
				}
			}
			candidates[text(order, "id")] = append(candidates[text(order, "id")], event)
			uses[text(event, "id")]++
		}
	}
	for _, order := range events {
		if text(order, "source_kind") != "bank_api" || text(order, "obligation_kind") != "payment_order" {
			continue
		}
		matches := candidates[text(order, "id")]
		if original, exists := order["link_status"]; exists {
			order["_original_link_status"] = original
		}
		order["_payment_order_link"] = true
		if len(matches) == 1 && uses[text(matches[0], "id")] == 1 {
			event := matches[0]
			order["link_original_status"] = order["status"]
			order["status"] = "linked"
			order["linked_event_id"] = event["id"]
			order["link_status"] = "linked"
			event["linked_sources"] = append(docs(event["linked_sources"]), Doc{"event_id": order["id"], "source_id": order["source_id"], "source": "bank_api", "external_id": order["external_id"]})
		} else if len(matches) > 0 {
			order["link_status"] = "ambiguous"
		} else if text(order, "related_event_id") != "" || text(order, "document_number") != "" {
			order["link_status"] = "unresolved"
		}
	}
	return events, nil
}

var invoiceReference = regexp.MustCompile(`(?i)(?:invoice|сч[её]т(?:а|у)?)\s*[№#]?\s*([\p{L}\p{N}][\p{L}\p{N}/_.-]*)`)

func referencedInvoiceNumber(title string) string {
	if match := invoiceReference.FindStringSubmatch(title); len(match) > 1 {
		return strings.TrimRight(match[1], ".,;")
	}
	return ""
}
func orderReferencesInvoice(order Doc, number string) bool {
	if reference := text(order, "document_number"); reference != "" {
		return strings.EqualFold(strings.TrimSpace(reference), strings.TrimSpace(number))
	}
	return strings.EqualFold(referencedInvoiceNumber(text(order, "title")), strings.TrimSpace(number))
}
