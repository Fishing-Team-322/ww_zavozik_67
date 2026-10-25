/** Content fields only. Compact shell controls retain their legacy sizing. */
export type FieldSize = "sm" | "md" | "lg";

export const fieldTextClass = "text-[13px] font-normal leading-5";

export const fieldSizeClasses: Record<FieldSize, string> = {
  sm: `h-8 px-2 ${fieldTextClass}`,
  md: `h-10 px-3 ${fieldTextClass}`,
  lg: `h-11 px-4 ${fieldTextClass}`,
};

export const fieldLabelClass = "mb-1.5 block text-xs font-medium leading-4";
export const fieldHelpClass = "pt-1.5 text-xs leading-[18px] text-[color:var(--text-secondary)]";
export const fieldErrorClass = "pt-1.5 text-xs leading-[18px] text-[color:var(--status-danger-fg)]";

export const fieldEndPadding: Record<FieldSize, string> = {
  sm: "pr-9",
  md: "pr-10",
  lg: "pr-11",
};

export const fieldEndPosition: Record<FieldSize, string> = {
  sm: "right-1.5 h-6 w-6",
  md: "right-2 h-6 w-6",
  lg: "right-2.5 h-7 w-7",
};
