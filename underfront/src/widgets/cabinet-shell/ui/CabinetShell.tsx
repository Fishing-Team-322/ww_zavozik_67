"use client";

import { usePathname } from "next/navigation";
import { SidebarShell, type SidebarShellProps } from "./SidebarShell";

/** Постоянная оболочка приложения, монтируется в корневом layout. */
export function CabinetShell(props: SidebarShellProps) {
  const pathname = usePathname();
  if (["/login", "/register", "/forgot-password", "/reset-password", "/auth/callback"].includes(pathname || '')) return <>{props.children}</>;

  return <SidebarShell {...props} />;
}
