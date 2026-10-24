"use client";

import { Loader2, Search } from "lucide-react";
import { Input, type InputProps } from "@/src/shared/ui/input";

export interface SearchInputProps extends Omit<InputProps, "type" | "startAdornment"> {
  loading?: boolean;
  label?: string;
}

/** Search and loading icons are anchored to the field, independent of help/error height. */
export function SearchInput({ loading = false, disabled, inputSize = "md", ...props }: SearchInputProps) {
  return (
    <Input
      {...props}
      type="search"
      inputSize={inputSize}
      disabled={disabled || loading}
      startAdornment={<Search size={16} strokeWidth={2} />}
      endAdornment={loading ? <Loader2 size={16} strokeWidth={2.25} className="animate-spin" /> : props.endAdornment}
    />
  );
}
