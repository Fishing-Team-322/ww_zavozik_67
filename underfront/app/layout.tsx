import type { Metadata } from "next";
import { CabinetShell } from "@/src/widgets/cabinet-shell";
import { SidebarNavStateProvider } from "@/src/widgets/cabinet-shell";
import { CompanyProvider } from "@/src/features/company-context/CompanyProvider";
import { AuthProvider } from "@/src/features/auth/model/AuthProvider";
import { DataUpdateMonitor } from "@/src/widgets/company-updates/DataUpdateMonitor";
import "@fontsource-variable/inter/wght.css";
import "@fontsource-variable/inter/wght-italic.css";
import "./globals.css";
import "./puls-accent.css";

export const metadata: Metadata = {
  title: "ПУЛЬС — финансовый радар",
  description: "Прогноз денежных потоков малого бизнеса",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" data-theme="light" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: "(function(){try{var t=localStorage.getItem('puls-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t)}catch(e){}})();" }} />
      </head>
      <body><AuthProvider><CompanyProvider><SidebarNavStateProvider><CabinetShell><DataUpdateMonitor />{children}</CabinetShell></SidebarNavStateProvider></CompanyProvider></AuthProvider></body>
    </html>
  );
}
