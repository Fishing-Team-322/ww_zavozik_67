package platform

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"time"

	"golang.org/x/oauth2"
)

type Provider struct {
	Config      oauth2.Config
	UserInfoURL string
}

func Providers(googleID, googleSecret, yandexID, yandexSecret, publicURL string) map[string]Provider {
	out := map[string]Provider{}
	if googleID != "" && googleSecret != "" {
		out["google"] = Provider{Config: oauth2.Config{ClientID: googleID, ClientSecret: googleSecret, RedirectURL: publicURL + "/v1/auth/oauth/google/callback", Scopes: []string{"openid", "email"}, Endpoint: oauth2.Endpoint{AuthURL: "https://accounts.google.com/o/oauth2/v2/auth", TokenURL: "https://oauth2.googleapis.com/token"}}, UserInfoURL: "https://openidconnect.googleapis.com/v1/userinfo"}
	}
	if yandexID != "" && yandexSecret != "" {
		out["yandex"] = Provider{Config: oauth2.Config{ClientID: yandexID, ClientSecret: yandexSecret, RedirectURL: publicURL + "/v1/auth/oauth/yandex/callback", Scopes: []string{"login:email"}, Endpoint: oauth2.Endpoint{AuthURL: "https://oauth.yandex.com/authorize", TokenURL: "https://oauth.yandex.com/token", AuthStyle: oauth2.AuthStyleInHeader}}, UserInfoURL: "https://login.yandex.ru/info?format=json"}
	}
	return out
}
func (s *Service) OAuthStart(ctx context.Context, name string, consent bool) (url, state string, err error) {
	p, ok := s.Providers[name]
	if !ok {
		return "", "", Fail(404, "provider_unavailable", "Этот способ входа не настроен")
	}
	if !consent {
		return "", "", Fail(400, "consent_required", "Нужно согласие на обработку персональных данных")
	}
	state = RandomToken()
	verifier := oauth2.GenerateVerifier()
	if err = s.Repo.SaveOAuthFlow(ctx, Digest(state), name, verifier, time.Now().UTC().Add(10*time.Minute)); err != nil {
		return "", "", err
	}
	return p.Config.AuthCodeURL(state, oauth2.S256ChallengeOption(verifier)), state, nil
}
func (s *Service) OAuthFinish(ctx context.Context, name, state, code string) (User, error) {
	p, ok := s.Providers[name]
	if !ok {
		return User{}, Fail(404, "provider_unavailable", "Этот способ входа не настроен")
	}
	if len(code) == 0 || len(code) > 4096 || len(state) < 20 || len(state) > 256 {
		return User{}, Fail(400, "invalid_oauth_response", "Повторите вход через сервис")
	}
	verifier, err := s.Repo.TakeOAuthFlow(ctx, Digest(state), name)
	if err != nil {
		return User{}, err
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	client := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	ctx = context.WithValue(ctx, oauth2.HTTPClient, client)
	token, err := p.Config.Exchange(ctx, code, oauth2.VerifierOption(verifier))
	if err != nil {
		return User{}, Fail(502, "oauth_failed", "Сервис входа не ответил. Повторите попытку")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, p.UserInfoURL, nil)
	if err != nil {
		return User{}, err
	}
	prefix := "Bearer "
	if name == "yandex" {
		prefix = "OAuth "
	}
	req.Header.Set("Authorization", prefix+token.AccessToken)
	res, err := client.Do(req)
	if err != nil {
		return User{}, Fail(502, "oauth_failed", "Не удалось получить профиль")
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return User{}, Fail(502, "oauth_failed", "Не удалось получить профиль")
	}
	var profile struct {
		Subject      string `json:"sub"`
		ID           string `json:"id"`
		Email        string `json:"email"`
		DefaultEmail string `json:"default_email"`
		Verified     bool   `json:"email_verified"`
		ClientID     string `json:"client_id"`
	}
	if err = json.NewDecoder(io.LimitReader(res.Body, 64*1024)).Decode(&profile); err != nil {
		return User{}, Fail(502, "oauth_failed", "Некорректный ответ сервиса входа")
	}
	subject, email := profile.Subject, profile.Email
	if name == "google" && !profile.Verified {
		return User{}, Fail(400, "unverified_email", "Подтвердите email у сервиса входа")
	}
	if name == "yandex" {
		subject, email = profile.ID, profile.DefaultEmail
		if profile.ClientID != "" && profile.ClientID != p.Config.ClientID {
			return User{}, Fail(400, "invalid_oauth_response", "Некорректное приложение входа")
		}
	}
	email, err = NormalizeEmail(email)
	if err != nil || subject == "" || len(subject) > 255 {
		return User{}, Fail(400, "missing_oauth_email", "Сервис не передал подтверждённый профиль и email")
	}
	// Never merge identities based on email: password accounts may have unverified mailboxes.
	return s.Repo.OAuthUser(ctx, name, subject, email)
}
