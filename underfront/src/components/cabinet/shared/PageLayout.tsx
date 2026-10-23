"use client";

import { Fragment, type ReactNode, useContext } from "react";
import { createPortal } from "react-dom";
import { Tabs, type TabItem } from "@/src/components/ui/tabs";
import { cn } from "@/src/lib/cn";
import { PageSidePanelSlotContext } from "./PageSidePanelSlot";

export type PageContentWidth = "full" | "narrow";

export type PageLayoutProps = {
  tabs?: TabItem[];
  defaultTab?: string;
  activeTab?: string;
  onTabChange?: (value: string) => void;
  tabsClassName?: string;
  tabListClassName?: string;
  contentWidth?: PageContentWidth;
  className?: string;
  contentClassName?: string;
  sidePanel?: ReactNode;
  children?: ReactNode;
};

const contentWidthClasses: Record<PageContentWidth, string> = {
  full: "w-full",
  narrow: "w-[1200px] max-w-full",
};

/**
 * Собирает содержимое страницы, необязательные вкладки и боковую панель.
 * Общая навигационная цепочка находится в постоянном CabinetShell.
 */
export function PageLayout({
  tabs,
  defaultTab,
  activeTab,
  onTabChange,
  tabsClassName,
  tabListClassName,
  contentWidth = "full",
  className,
  contentClassName,
  sidePanel,
  children,
}: PageLayoutProps) {
  const sidePanelSlot = useContext(PageSidePanelSlotContext);
  const contentClasses = cn(
    contentWidthClasses[contentWidth],
    contentClassName
  );

  const page = (
    <div className={cn("min-w-0 space-y-5", className)}>
      {tabs?.length ? (
        <Tabs
          tabs={tabs}
          defaultValue={defaultTab}
          value={activeTab}
          onValueChange={onTabChange}
          className={tabsClassName}
          listClassName={tabListClassName}
          contentClassName={contentClasses}
        />
      ) : (
        <div className={contentClasses}>{children}</div>
      )}
    </div>
  );

  if (!sidePanel) return page;

  return (
    <Fragment>
      {page}
      {sidePanelSlot ? (
        createPortal(sidePanel, sidePanelSlot)
      ) : (
        <div className="mt-5">{sidePanel}</div>
      )}
    </Fragment>
  );
}
