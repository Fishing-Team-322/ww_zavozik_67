package httpapi

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"mime"
	"net/http"
	"sort"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
)

// reply keeps the strict generated interfaces while serializing the shared DTOs once.
type reply struct {
	dataBytes      []byte
	filename, mime string
	status         int
	data           any
	cookies        []*http.Cookie
	location       string
}

func (a reply) write(w http.ResponseWriter) error {
	if a.filename != "" {
		w.Header().Set("Content-Type", a.mime)
		w.Header().Set("Content-Disposition", mime.FormatMediaType("attachment", map[string]string{"filename": a.filename}))
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(a.status)
		_, e := w.Write(a.dataBytes)
		return e
	}
	w.Header().Set("Cache-Control", "no-store")
	for _, cookie := range a.cookies {
		http.SetCookie(w, cookie)
	}
	if a.location != "" {
		w.Header().Set("Location", a.location)
	}
	if a.data != nil {
		w.Header().Set("Content-Type", "application/json")
	}
	w.WriteHeader(a.status)
	if a.data != nil {
		return json.NewEncoder(w).Encode(a.data)
	}
	return nil
}
func (s *Server) platformError(w http.ResponseWriter, err error) {
	var e *platform.Error
	if errors.As(err, &e) {
		if e.Status == 401 {
			w.Header().Set("WWW-Authenticate", "Bearer")
		}
		writeError(w, e.Status, e.Code, e.Message)
		return
	}
	s.Log.Error("platform operation failed")
	writeError(w, 500, "internal", "Внутренняя ошибка")
}
func (s *Server) cookie(name, value string, age int) *http.Cookie {
	path := "/v1/auth"
	if name == "zavozik_oauth_state" {
		path = "/v1/auth/oauth"
	}
	c := &http.Cookie{Name: name, Value: value, Path: path, HttpOnly: true, Secure: s.Accounts.SecureCookies, SameSite: http.SameSiteLaxMode, MaxAge: age}
	if age < 0 {
		c.Expires = time.Unix(1, 0)
	} else {
		c.Expires = time.Now().Add(time.Duration(age) * time.Second)
	}
	return c
}
func (s *Server) sessionReply(ctx context.Context, user platform.User, status int) (reply, error) {
	token, refresh, err := s.Accounts.Issue(ctx, user, request(ctx).UserAgent())
	if err != nil {
		return reply{}, err
	}
	return reply{status: status, data: token, cookies: []*http.Cookie{s.cookie("zavozik_refresh", refresh, 30*24*3600)}}, nil
}
func (s *Server) Register(ctx context.Context, r RegisterRequestObject) (RegisterResponseObject, error) {
	u, err := s.Accounts.Register(ctx, string(r.Body.Email), r.Body.Password, bool(r.Body.ConsentPd))
	if err != nil {
		return nil, err
	}
	return s.sessionReply(ctx, u, 201)
}
func (s *Server) Login(ctx context.Context, r LoginRequestObject) (LoginResponseObject, error) {
	u, err := s.Accounts.Login(ctx, string(r.Body.Email), r.Body.Password)
	if err != nil {
		return nil, err
	}
	return s.sessionReply(ctx, u, 200)
}
func (s *Server) Refresh(ctx context.Context, _ RefreshRequestObject) (RefreshResponseObject, error) {
	c, err := request(ctx).Cookie("zavozik_refresh")
	if err != nil {
		return nil, platform.ErrUnauthorized
	}
	token, next, err := s.Accounts.Refresh(ctx, c.Value)
	if err != nil {
		return nil, err
	}
	return reply{status: 200, data: token, cookies: []*http.Cookie{s.cookie("zavozik_refresh", next, 30*24*3600)}}, nil
}
func (s *Server) Logout(ctx context.Context, _ LogoutRequestObject) (LogoutResponseObject, error) {
	p := principal(ctx)
	if err := s.Accounts.Repo.RevokeSession(ctx, p.User.ID, p.Session.ID); err != nil {
		return nil, err
	}
	return reply{status: 204, cookies: []*http.Cookie{s.cookie("zavozik_refresh", "", -1)}}, nil
}
func (s *Server) ForgotPassword(ctx context.Context, r ForgotPasswordRequestObject) (ForgotPasswordResponseObject, error) {
	if err := s.Accounts.Forgot(ctx, string(r.Body.Email)); err != nil {
		return nil, err
	}
	return reply{status: 204}, nil
}
func (s *Server) ResetPassword(ctx context.Context, r ResetPasswordRequestObject) (ResetPasswordResponseObject, error) {
	if err := s.Accounts.Reset(ctx, r.Body.Token, r.Body.NewPassword); err != nil {
		return nil, err
	}
	return reply{status: 204, cookies: []*http.Cookie{s.cookie("zavozik_refresh", "", -1)}}, nil
}
func (s *Server) GetMe(ctx context.Context, _ GetMeRequestObject) (GetMeResponseObject, error) {
	u := principal(ctx).User
	companies, err := s.Accounts.Repo.ListCompanies(ctx, u.ID)
	if err != nil {
		return nil, err
	}
	return reply{status: 200, data: struct {
		platform.User
		Companies []platform.Company `json:"companies"`
	}{u, companies}}, nil
}
func (s *Server) ChangePassword(ctx context.Context, r ChangePasswordRequestObject) (ChangePasswordResponseObject, error) {
	if err := s.Accounts.ChangePassword(ctx, principal(ctx), r.Body.OldPassword, r.Body.NewPassword); err != nil {
		return nil, err
	}
	return reply{status: 204, cookies: []*http.Cookie{s.cookie("zavozik_refresh", "", -1)}}, nil
}
func (s *Server) ListSessions(ctx context.Context, _ ListSessionsRequestObject) (ListSessionsResponseObject, error) {
	p := principal(ctx)
	sessions, err := s.Accounts.Repo.ListSessions(ctx, p.User.ID)
	if err != nil {
		return nil, err
	}
	for i := range sessions {
		sessions[i].Current = sessions[i].ID == p.Session.ID
	}
	return reply{status: 200, data: sessions}, nil
}
func (s *Server) RevokeSession(ctx context.Context, r RevokeSessionRequestObject) (RevokeSessionResponseObject, error) {
	p := principal(ctx)
	id := r.SessionId.String()
	if err := s.Accounts.Repo.RevokeSession(ctx, p.User.ID, id); err != nil {
		return nil, err
	}
	out := reply{status: 204}
	if p.Session.ID == id {
		out.cookies = []*http.Cookie{s.cookie("zavozik_refresh", "", -1)}
	}
	return out, nil
}
func (s *Server) ListAuthProviders(_ context.Context, _ ListAuthProvidersRequestObject) (ListAuthProvidersResponseObject, error) {
	names := []string{}
	if s.Accounts != nil {
		for name := range s.Accounts.Providers {
			names = append(names, name)
		}
	}
	sort.Strings(names)
	return reply{status: 200, data: names}, nil
}
func (s *Server) StartOAuth(ctx context.Context, r StartOAuthRequestObject) (StartOAuthResponseObject, error) {
	url, state, err := s.Accounts.OAuthStart(ctx, string(r.Provider), r.Params.ConsentPd)
	if err != nil {
		return nil, err
	}
	return reply{status: 302, location: url, cookies: []*http.Cookie{s.cookie("zavozik_oauth_state", state, 600)}}, nil
}
func (s *Server) FinishOAuth(ctx context.Context, r FinishOAuthRequestObject) (FinishOAuthResponseObject, error) {
	if r.Params.Error != nil {
		return nil, platform.Fail(400, "oauth_cancelled", "Вход через сервис отменён")
	}
	if r.Params.Code == nil || r.Params.State == nil {
		return nil, platform.Fail(400, "invalid_oauth_response", "Повторите вход через сервис")
	}
	cookie, err := request(ctx).Cookie("zavozik_oauth_state")
	if err != nil || subtle.ConstantTimeCompare([]byte(cookie.Value), []byte(*r.Params.State)) != 1 {
		return nil, platform.Fail(400, "invalid_oauth_state", "Повторите вход через сервис")
	}
	u, err := s.Accounts.OAuthFinish(ctx, string(r.Provider), *r.Params.State, *r.Params.Code)
	if err != nil {
		return nil, err
	}
	out, err := s.sessionReply(ctx, u, 302)
	if err != nil {
		return nil, err
	}
	out.data = nil
	out.location = s.Accounts.FrontendURL + "/auth/callback"
	out.cookies = append(out.cookies, s.cookie("zavozik_oauth_state", "", -1))
	return out, nil
}
func (s *Server) ListCompanies(ctx context.Context, _ ListCompaniesRequestObject) (ListCompaniesResponseObject, error) {
	c, err := s.Accounts.Repo.ListCompanies(ctx, principal(ctx).User.ID)
	if err != nil {
		return nil, err
	}
	return reply{status: 200, data: c}, nil
}
func (s *Server) CreateCompany(ctx context.Context, r CreateCompanyRequestObject) (CreateCompanyResponseObject, error) {
	b := r.Body
	c := platform.Company{Name: b.Name, INN: b.Inn, LegalForm: string(b.LegalForm), Industry: b.Industry}
	if b.Reserve != nil {
		c.Reserve = float64(*b.Reserve)
	}
	if b.TaxRegime != nil {
		if *b.TaxRegime == "" {
			return nil, platform.Fail(400, "invalid_company", "Неизвестный налоговый режим")
		}
		c.TaxRegime = string(*b.TaxRegime)
	}
	if b.DefaultHorizon != nil {
		if *b.DefaultHorizon == 0 {
			return nil, platform.Fail(400, "invalid_company", "Горизонт: 30, 60 или 90 дней")
		}
		c.DefaultHorizon = int(*b.DefaultHorizon)
	}
	if err := platform.ValidateCompany(&c); err != nil {
		return nil, err
	}
	c, err := s.Accounts.Repo.CreateCompany(ctx, principal(ctx).User.ID, c)
	if err != nil {
		return nil, err
	}
	return reply{status: 201, data: c}, nil
}
func (s *Server) GetCompany(ctx context.Context, r GetCompanyRequestObject) (GetCompanyResponseObject, error) {
	c, err := s.Accounts.Repo.GetCompany(ctx, principal(ctx).User.ID, r.CompanyId.String())
	if err != nil {
		return nil, err
	}
	return reply{status: 200, data: c}, nil
}
func (s *Server) UpdateCompany(ctx context.Context, r UpdateCompanyRequestObject) (UpdateCompanyResponseObject, error) {
	uid := principal(ctx).User.ID
	c, err := s.Accounts.Repo.GetCompany(ctx, uid, r.CompanyId.String())
	if err != nil {
		return nil, err
	}
	b := r.Body
	if b.Name != nil {
		c.Name = *b.Name
	}
	if b.Industry != nil {
		c.Industry = *b.Industry
	}
	if b.LegalForm != nil {
		c.LegalForm = string(*b.LegalForm)
	}
	if _, ok := rawBody(ctx)["inn"]; ok {
		c.INN = b.Inn
	}
	if b.Reserve != nil {
		c.Reserve = float64(*b.Reserve)
	}
	if b.TaxRegime != nil {
		if *b.TaxRegime == "" {
			return nil, platform.Fail(400, "invalid_company", "Неизвестный налоговый режим")
		}
		c.TaxRegime = string(*b.TaxRegime)
	}
	if b.DefaultHorizon != nil {
		if *b.DefaultHorizon == 0 {
			return nil, platform.Fail(400, "invalid_company", "Горизонт: 30, 60 или 90 дней")
		}
		c.DefaultHorizon = int(*b.DefaultHorizon)
	}
	if err = platform.ValidateCompany(&c); err != nil {
		return nil, err
	}
	c, err = s.Accounts.Repo.UpdateCompany(ctx, uid, c)
	if err != nil {
		return nil, err
	}
	return reply{status: 200, data: c}, nil
}
func (s *Server) DeleteCompany(ctx context.Context, r DeleteCompanyRequestObject) (DeleteCompanyResponseObject, error) {
	if err := s.Accounts.Repo.DeleteCompany(ctx, principal(ctx).User.ID, r.CompanyId.String(), r.Body.ConfirmName); err != nil {
		return nil, err
	}
	return reply{status: 204}, nil
}
func (s *Server) GetCompanyState(ctx context.Context, r GetCompanyStateRequestObject) (GetCompanyStateResponseObject, error) {
	state, err := s.Accounts.Repo.GetState(ctx, principal(ctx).User.ID, r.CompanyId.String())
	if err != nil {
		return nil, err
	}
	return reply{status: 200, data: state}, nil
}
func (s *Server) PutCompanyState(ctx context.Context, r PutCompanyStateRequestObject) (PutCompanyStateResponseObject, error) {
	state, err := s.Accounts.Repo.PutState(ctx, principal(ctx).User.ID, r.CompanyId.String(), r.Body.ExpectedVersion, rawBody(ctx)["data"])
	if err != nil {
		return nil, err
	}
	return reply{status: 200, data: state}, nil
}
