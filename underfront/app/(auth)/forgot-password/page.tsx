import type { Metadata } from "next";
import { AuthPage } from "@/src/features/auth";

export const metadata: Metadata = { title: "Восстановление пароля — ПУЛЬС" };

export default function ForgotPasswordPage() {
  return <AuthPage mode="recover" />;
}
