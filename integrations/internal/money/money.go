package money

import (
	"errors"
	"math"
	"strconv"
	"strings"
)

var ErrInvalid = errors.New("invalid amount")

// Parse converts a nonnegative decimal number of rubles to exact kopecks.
func Parse(s string) (int64, error) {
	s = strings.TrimSpace(s)
	if s == "" || strings.HasPrefix(s, "-") || strings.HasPrefix(s, "+") {
		return 0, ErrInvalid
	}
	s = strings.ReplaceAll(s, ",", ".")
	parts := strings.Split(s, ".")
	if len(parts) > 2 || parts[0] == "" {
		return 0, ErrInvalid
	}
	for _, p := range parts {
		if p == "" {
			return 0, ErrInvalid
		}
		for _, c := range p {
			if c < '0' || c > '9' {
				return 0, ErrInvalid
			}
		}
	}
	if len(parts) == 2 && len(parts[1]) > 2 {
		return 0, ErrInvalid
	}
	rubles, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		return 0, ErrInvalid
	}
	kopecks := int64(0)
	if len(parts) == 2 {
		kopecks, _ = strconv.ParseInt(parts[1], 10, 64)
		if len(parts[1]) == 1 {
			kopecks *= 10
		}
	}
	if rubles > (math.MaxInt64-kopecks)/100 {
		return 0, ErrInvalid
	}
	return rubles*100 + kopecks, nil
}
