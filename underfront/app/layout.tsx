import type { Metadata } from "next";
import { CabinetShell } from "@/src/components/cabinet/shared/CabinetShell";
import { SidebarNavStateProvider } from "@/src/components/cabinet/shared/SidebarNavStateProvider";
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
      <body><SidebarNavStateProvider><CabinetShell>{children}</CabinetShell></SidebarNavStateProvider></body>
    </html>
  );
}
