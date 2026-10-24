import type { Company } from "@/src/entities/company";

export interface AuthUser {
  id: string;
  email: string;
  role: "owner" | "admin";
  created_at: string;
  companies: Company[];
}

export type AuthStatus = "loading" | "authenticated" | "guest" | "error";
