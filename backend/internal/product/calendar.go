package product

import (
	"embed"
	"encoding/json"
	"strconv"
	"strings"
	"time"
)

// The same production calendar snapshots are used by the ML module.
//
//go:embed calendar_data/*.json
var calendarFiles embed.FS
var nonWorkdays = loadCalendar()

func loadCalendar() map[int]map[int]map[int]bool {
	out := map[int]map[int]map[int]bool{}
	files, _ := calendarFiles.ReadDir("calendar_data")
	for _, file := range files {
		data, e := calendarFiles.ReadFile("calendar_data/" + file.Name())
		if e != nil {
			continue
		}
		var c struct {
			Year   int `json:"year"`
			Months []struct {
				Month int    `json:"month"`
				Days  string `json:"days"`
			} `json:"months"`
		}
		if json.Unmarshal(data, &c) != nil {
			continue
		}
		out[c.Year] = map[int]map[int]bool{}
		for _, month := range c.Months {
			out[c.Year][month.Month] = map[int]bool{}
			for _, raw := range strings.Split(month.Days, ",") {
				n, e := strconv.Atoi(strings.TrimRight(raw, "*+"))
				if e == nil {
					out[c.Year][month.Month][n] = !strings.HasSuffix(raw, "*")
				}
			}
		}
	}
	return out
}
func isWorkday(d time.Time) bool {
	if months, yes := nonWorkdays[d.Year()]; yes {
		return !months[int(d.Month())][d.Day()]
	}
	return d.Weekday() != time.Saturday && d.Weekday() != time.Sunday
}
