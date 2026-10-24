package httpapi

import "net/http"

func (a reply) VisitRegisterResponse(w http.ResponseWriter) error          { return a.write(w) }
func (a reply) VisitLoginResponse(w http.ResponseWriter) error             { return a.write(w) }
func (a reply) VisitRefreshResponse(w http.ResponseWriter) error           { return a.write(w) }
func (a reply) VisitLogoutResponse(w http.ResponseWriter) error            { return a.write(w) }
func (a reply) VisitForgotPasswordResponse(w http.ResponseWriter) error    { return a.write(w) }
func (a reply) VisitResetPasswordResponse(w http.ResponseWriter) error     { return a.write(w) }
func (a reply) VisitGetMeResponse(w http.ResponseWriter) error             { return a.write(w) }
func (a reply) VisitChangePasswordResponse(w http.ResponseWriter) error    { return a.write(w) }
func (a reply) VisitListSessionsResponse(w http.ResponseWriter) error      { return a.write(w) }
func (a reply) VisitRevokeSessionResponse(w http.ResponseWriter) error     { return a.write(w) }
func (a reply) VisitListAuthProvidersResponse(w http.ResponseWriter) error { return a.write(w) }
func (a reply) VisitStartOAuthResponse(w http.ResponseWriter) error        { return a.write(w) }
func (a reply) VisitFinishOAuthResponse(w http.ResponseWriter) error       { return a.write(w) }
func (a reply) VisitListCompaniesResponse(w http.ResponseWriter) error     { return a.write(w) }
func (a reply) VisitCreateCompanyResponse(w http.ResponseWriter) error     { return a.write(w) }
func (a reply) VisitGetCompanyResponse(w http.ResponseWriter) error        { return a.write(w) }
func (a reply) VisitUpdateCompanyResponse(w http.ResponseWriter) error     { return a.write(w) }
func (a reply) VisitDeleteCompanyResponse(w http.ResponseWriter) error     { return a.write(w) }
func (a reply) VisitGetCompanyStateResponse(w http.ResponseWriter) error   { return a.write(w) }
func (a reply) VisitPutCompanyStateResponse(w http.ResponseWriter) error   { return a.write(w) }
