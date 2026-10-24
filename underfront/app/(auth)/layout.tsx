import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return <div className="relative min-h-screen">
    <div className="pointer-events-none absolute left-4 top-5 z-10 text-[13px] font-semibold tracking-[0.12em] text-[color:var(--nav-item-active-text)] sm:left-8 sm:top-7">ПУЛЬС</div>
    {children}
  </div>;
}
