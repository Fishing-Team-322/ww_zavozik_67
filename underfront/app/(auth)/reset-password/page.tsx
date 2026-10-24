import type { Metadata } from "next";
import { AuthPage } from "@/src/features/auth";

export const metadata: Metadata = { title: "Новый пароль — ПУЛЬС" };

export default function ResetPasswordPage() {
  return <AuthPage mode="reset" />;
}
