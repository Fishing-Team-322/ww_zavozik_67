"use client";

import { SidebarShell, type SidebarShellProps } from "./SidebarShell";

/** Постоянная оболочка приложения, монтируется в корневом layout. */
export function CabinetShell(props: SidebarShellProps) {
  return <SidebarShell {...props} />;
}
