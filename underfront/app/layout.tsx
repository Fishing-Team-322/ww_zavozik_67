import type { Metadata } from "next";
import { SessionProvider } from "@/src/features/auth";
import { CabinetShell } from "@/src/widgets/cabinet-shell";
import { SidebarNavStateProvider } from "@/src/widgets/cabinet-shell";
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
      <body><SessionProvider><SidebarNavStateProvider><CabinetShell>{children}</CabinetShell></SidebarNavStateProvider></SessionProvider></body>
    </html>
  );
}
