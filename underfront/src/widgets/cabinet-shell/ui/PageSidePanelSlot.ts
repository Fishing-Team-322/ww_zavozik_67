"use client";

import { createContext } from "react";

/** Слот внешней боковой карточки, принадлежащей текущему PageLayout. */
export const PageSidePanelSlotContext = createContext<HTMLElement | null>(null);
