import type { Metadata } from "next";
import { AuthPage } from "@/src/features/auth";

export const metadata: Metadata = { title: "Вход — ПУЛЬС" };

export default function LoginPage() {
  return <AuthPage mode="login" />;
}
