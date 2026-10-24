import type { Metadata } from "next";
import { AuthPage } from "@/src/features/auth";

export const metadata: Metadata = { title: "Регистрация — PULSE" };

export default function RegisterPage() {
  return <AuthPage mode="register" />;
}
