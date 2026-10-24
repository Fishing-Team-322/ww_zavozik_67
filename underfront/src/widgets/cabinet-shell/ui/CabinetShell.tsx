"use client";

import { usePathname } from "next/navigation";
import { SidebarShell, type SidebarShellProps } from "./SidebarShell";

/** Постоянная оболочка приложения, монтируется в корневом layout. */
export function CabinetShell(props: SidebarShellProps) {
  const pathname = usePathname();
  if (pathname === "/login" || pathname === "/register" || pathname === "/forgot-password") return <>{props.children}</>;

  return <SidebarShell {...props} />;
}
