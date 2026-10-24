package product

import (
	"net/http/httptest"
	"net/url"
	"testing"
)

func TestPageOperationsNewestFirstAndStableCursor(t *testing.T) {
	rows := []Doc{
		{"id": "b", "date": "2015-01-26"},
		{"id": "a", "date": "2026-10-24"},
		{"id": "c", "date": "2026-10-24"},
		{"id": "d", "date": "2015-02-24"},
	}
	request := httptest.NewRequest("GET", "/operations?limit=2", nil)
	first, err := pageOperations(rows, request)
	if err != nil {
		t.Fatal(err)
	}
	items := first["items"].([]Doc)
	if text(items[0], "id") != "c" || text(items[1], "id") != "a" {
		t.Fatalf("first page order: %v", items)
	}
	cursor := first["next_cursor"].(string)
	request = httptest.NewRequest("GET", "/operations?limit=2&cursor="+url.QueryEscape(cursor), nil)
	second, err := pageOperations(rows, request)
	if err != nil {
		t.Fatal(err)
	}
	items = second["items"].([]Doc)
	if text(items[0], "id") != "d" || text(items[1], "id") != "b" || second["next_cursor"] != nil {
		t.Fatalf("second page: %v", second)
	}
}
