package platform

import (
	"context"
	"log/slog"
	"math"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/bridge"
	"github.com/golang-jwt/jwt/v5"
)

type Repository interface {
	CreateUser(context.Context, string, *string) (User, error)
	UserByEmail(context.Context, string) (User, error)
	NewSession(context.Context, User, string, string, time.Time) (Session, error)
	RotateSession(context.Context, string, string) (Principal, error)
	Principal(context.Context, string, string) (Principal, error)
	RevokeSession(context.Context, string, string) error
	ListSessions(context.Context, string) ([]Session, error)
	ChangePassword(context.Context, string, *string, string) error
	SaveReset(context.Context, string, string, time.Time) (User, error)
	ResetPassword(context.Context, string, string) error
	SaveOAuthFlow(context.Context, string, string, string, time.Time) error
	TakeOAuthFlow(context.Context, string, string) (string, error)
	OAuthUser(context.Context, string, string, string) (User, error)
	ListCompanies(context.Context, string) ([]Company, error)
	CreateCompany(context.Context, string, Company) (Company, error)
	GetCompany(context.Context, string, string) (Company, error)
	UpdateCompany(context.Context, string, Company) (Company, error)
	DeleteCompany(context.Context, string, string, string) error
	GetState(context.Context, string, string) (State, error)
	PutState(context.Context, string, string, int64, []byte) (State, error)
}
type Mailer interface {
	SendReset(context.Context, string, string) error
}
type Service struct {
	Log                    *slog.Logger
	Repo                   Repository
	Secret                 []byte
	Mailer                 Mailer
	Providers              map[string]Provider
	PublicURL, FrontendURL string
	SecureCookies          bool
	// Filled on construction; one fixed hash masks unknown-user password timings.
	dummyHash string
}

func New(repo Repository, secret string) (*Service, error) {
	if len(secret) < 32 {
		return nil, Fail(503, "invalid_config", "JWT_SECRET должен содержать минимум 32 байта")
	}
	hash, err := HashPassword(RandomToken())
	if err != nil {
		return nil, err
	}
	return &Service{Repo: repo, Secret: []byte(secret), dummyHash: hash}, nil
}
func (s *Service) Register(ctx context.Context, email, password string, consent bool) (User, error) {
	if !consent {
		return User{}, Fail(400, "consent_required", "Нужно согласие на обработку персональных данных")
	}
	email, err := NormalizeEmail(email)
	if err != nil {
		return User{}, err
	}
	hash, err := HashPassword(password)
	if err != nil {
		return User{}, err
	}
	return s.Repo.CreateUser(ctx, email, &hash)
}
func (s *Service) Login(ctx context.Context, email, password string) (User, error) {
	email, err := NormalizeEmail(email)
	if err != nil {
		return User{}, ErrCredentials
	}
	if len(password) > 256 {
		return User{}, ErrCredentials
	}
	user, err := s.Repo.UserByEmail(ctx, email)
	if err != nil && !IsStatus(err, 404) {
		return User{}, err
	}
	hash := s.dummyHash
	if err == nil && user.PasswordHash != nil {
		hash = *user.PasswordHash
	}
	valid := CheckPassword(hash, password)
	if err != nil || user.PasswordHash == nil || !valid {
		return User{}, ErrCredentials
	}
	return user, nil
}
func (s *Service) Issue(ctx context.Context, u User, device string) (Token, string, error) {
	refresh := RandomToken()
	if len(device) > 256 {
		device = device[:256]
	}
	sess, err := s.Repo.NewSession(ctx, u, device, Digest(refresh), time.Now().UTC().Add(30*24*time.Hour))
	if err != nil {
		return Token{}, "", err
	}
	token, err := s.sign(u, sess)
	return token, refresh, err
}
func (s *Service) Refresh(ctx context.Context, refresh string) (Token, string, error) {
	if len(refresh) < 20 || len(refresh) > 256 {
		return Token{}, "", ErrUnauthorized
	}
	next := RandomToken()
	p, err := s.Repo.RotateSession(ctx, Digest(refresh), Digest(next))
	if err != nil {
		return Token{}, "", err
	}
	token, err := s.sign(p.User, p.Session)
	return token, next, err
}

type claims struct {
	SessionID string `json:"sid"`
	Role      string `json:"role"`
	jwt.RegisteredClaims
}

func (s *Service) sign(u User, sess Session) (Token, error) {
	now := time.Now().UTC()
	until := now.Add(15 * time.Minute)
	if sess.ExpiresAt.Before(until) {
		until = sess.ExpiresAt
	}
	c := claims{SessionID: sess.ID, Role: u.Role, RegisteredClaims: jwt.RegisteredClaims{Issuer: "zavozik", Audience: jwt.ClaimStrings{"zavozik-api"}, Subject: u.ID, IssuedAt: jwt.NewNumericDate(now), ExpiresAt: jwt.NewNumericDate(until)}}
	raw, err := jwt.NewWithClaims(jwt.SigningMethodHS256, c).SignedString(s.Secret)
	return Token{raw, until}, err
}
func (s *Service) Authenticate(ctx context.Context, raw string) (Principal, error) {
	if len(raw) > 4096 {
		return Principal{}, ErrUnauthorized
	}
	c := &claims{}
	token, err := jwt.ParseWithClaims(raw, c, func(*jwt.Token) (any, error) { return s.Secret, nil }, jwt.WithValidMethods([]string{"HS256"}), jwt.WithIssuer("zavozik"), jwt.WithAudience("zavozik-api"), jwt.WithExpirationRequired(), jwt.WithIssuedAt())
	if err != nil || !token.Valid || c.Subject == "" || c.SessionID == "" {
		return Principal{}, ErrUnauthorized
	}
	return s.Repo.Principal(ctx, c.SessionID, c.Subject)
}
func (s *Service) ChangePassword(ctx context.Context, p Principal, old, next string) error {
	if err := ValidatePassword(next); err != nil {
		return err
	}
	if p.User.PasswordHash == nil || !CheckPassword(*p.User.PasswordHash, old) {
		return ErrCredentials
	}
	hash, err := HashPassword(next)
	if err != nil {
		return err
	}
	return s.Repo.ChangePassword(ctx, p.User.ID, p.User.PasswordHash, hash)
}
func (s *Service) Forgot(ctx context.Context, email string) error {
	email, err := NormalizeEmail(email)
	if err != nil {
		return err
	}
	if s.Mailer == nil {
		return Fail(503, "mail_unavailable", "Отправка почты пока не настроена")
	}
	raw := RandomToken()
	u, err := s.Repo.SaveReset(ctx, email, Digest(raw), time.Now().UTC().Add(30*time.Minute))
	if IsStatus(err, 404) {
		return nil
	}
	if err != nil {
		return err
	}
	// Never reveal whether a mailbox exists, including when delivery fails.
	// The sender uses a fixed configured frontend URL; no Host-header links.
	if err = s.Mailer.SendReset(ctx, u.Email, s.FrontendURL+"/reset-password#token="+raw); err != nil && s.Log != nil {
		s.Log.Warn("password reset mail delivery failed")
	}
	return nil
}
func (s *Service) Reset(ctx context.Context, raw, password string) error {
	if len(raw) < 20 || len(raw) > 256 {
		return Fail(400, "invalid_reset_token", "Ссылка недействительна или устарела")
	}
	hash, err := HashPassword(password)
	if err != nil {
		return err
	}
	return s.Repo.ResetPassword(ctx, Digest(raw), hash)
}
func ValidateCompany(c *Company) error {
	c.Name = strings.TrimSpace(c.Name)
	c.Industry = strings.TrimSpace(c.Industry)
	if c.Name == "" || len(c.Name) > 300 || c.Industry == "" || len(c.Industry) > 120 {
		return Fail(400, "invalid_company", "Укажите название и вид деятельности компании")
	}
	if c.LegalForm != "ООО" && c.LegalForm != "ИП" {
		return Fail(400, "invalid_company", "Допустимые формы: ООО и ИП")
	}
	if c.INN != nil {
		inn := strings.TrimSpace(*c.INN)
		c.INN = &inn
		if !bridge.ValidINN(inn) {
			return Fail(400, "invalid_inn", "Проверьте ИНН: нужны 10 или 12 цифр и корректная контрольная цифра")
		}
	}
	if c.TaxRegime == "" {
		c.TaxRegime = "unknown"
	}
	switch c.TaxRegime {
	case "usn6", "usn15", "osno", "eshn", "unknown":
	default:
		return Fail(400, "invalid_company", "Неизвестный налоговый режим")
	}
	if c.Reserve < 0 || c.Reserve > 99999999999999.99 || math.IsNaN(c.Reserve) || math.IsInf(c.Reserve, 0) || math.Abs(c.Reserve*100-math.Round(c.Reserve*100)) > 0.01 {
		return Fail(400, "invalid_company", "Резерв должен быть неотрицательным, с точностью до копейки")
	}
	if c.DefaultHorizon == 0 {
		c.DefaultHorizon = 30
	}
	if c.DefaultHorizon != 30 && c.DefaultHorizon != 60 && c.DefaultHorizon != 90 {
		return Fail(400, "invalid_company", "Горизонт: 30, 60 или 90 дней")
	}
	return nil
}
