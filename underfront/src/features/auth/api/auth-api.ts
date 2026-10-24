import { apiRequest } from "@/src/shared/api/client";
import type { AuthUser } from "../model/types";

export const authApi = {
  me: () => apiRequest<AuthUser>("/me"),
  forgotPassword: (email: string) => apiRequest<void>("/auth/password/forgot", {
    method: "POST", body: JSON.stringify({ email }),
  }, false),
  resetPassword: (token: string, newPassword: string) => apiRequest<void>("/auth/password/reset", {
    method: "POST", body: JSON.stringify({ token, new_password: newPassword }),
  }, false),
};
