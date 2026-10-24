// Package platform implements accounts, sessions and company-scoped cloud storage.
package platform

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/mail"
	"strings"
	"time"
)

type Error struct {
	Status        int
	Code, Message string
}

func (e *Error) Error() string                    { return e.Code }
func Fail(status int, code, message string) error { return &Error{status, code, message} }

var (
	ErrNotFound     = Fail(http.StatusNotFound, "not_found", "Данные не найдены")
	ErrUnauthorized = Fail(http.StatusUnauthorized, "unauthorized", "Войдите в аккаунт")
	ErrCredentials  = Fail(http.StatusUnauthorized, "invalid_credentials", "Неверный email или пароль")
	ErrConflict     = Fail(http.StatusConflict, "conflict", "Такие данные уже существуют")
)

func IsStatus(err error, status int) bool {
	var e *Error
	return errors.As(err, &e) && e.Status == status
}

type User struct {
	ID           string    `json:"id"`
	Email        string    `json:"email"`
	Role         string    `json:"role"`
	CreatedAt    time.Time `json:"created_at"`
	PasswordHash *string   `json:"-"`
}
type Session struct {
	ID         string    `json:"id"`
	UserID     string    `json:"-"`
	Device     string    `json:"device"`
	City       *string   `json:"city"`
	CreatedAt  time.Time `json:"created_at"`
	LastSeenAt time.Time `json:"last_seen_at"`
	ExpiresAt  time.Time `json:"expires_at"`
	Current    bool      `json:"current"`
}
type Principal struct {
	User    User
	Session Session
}
type Token struct {
	AccessToken string    `json:"access_token"`
	ExpiresAt   time.Time `json:"expires_at"`
}
type Company struct {
	ID             string     `json:"id"`
	Name           string     `json:"name"`
	INN            *string    `json:"inn"`
	LegalForm      string     `json:"legal_form"`
	Industry       string     `json:"industry"`
	TaxRegime      string     `json:"tax_regime"`
	Reserve        float64    `json:"reserve"`
	DefaultHorizon int        `json:"default_horizon"`
	DataAsOf       *time.Time `json:"data_as_of"`
	CreatedAt      time.Time  `json:"created_at"`
	UpdatedAt      time.Time  `json:"updated_at"`
}
type State struct {
	CompanyID string          `json:"company_id"`
	Version   int64           `json:"version"`
	Data      json.RawMessage `json:"data"`
	UpdatedAt time.Time       `json:"updated_at"`
}

func NormalizeEmail(email string) (string, error) {
	email = strings.ToLower(strings.TrimSpace(email))
	// A plain mailbox only: reject display names, whitespace and header delimiters.
	if len(email) > 254 || strings.ContainsAny(email, " \t\r\n<>,;") {
		return "", Fail(400, "invalid_email", "Укажите корректный email")
	}
	parts := strings.Split(email, "@")
	if len(parts) != 2 || len(parts[0]) == 0 || len(parts[0]) > 64 || !strings.Contains(parts[1], ".") || strings.HasPrefix(parts[1], ".") || strings.HasSuffix(parts[1], ".") {
		return "", Fail(400, "invalid_email", "Укажите корректный email")
	}
	parsed, err := mail.ParseAddress(email)
	if err != nil || parsed.Address != email {
		return "", Fail(400, "invalid_email", "Укажите корректный email")
	}
	return email, nil
}
