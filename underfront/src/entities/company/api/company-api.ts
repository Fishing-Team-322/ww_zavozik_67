import { apiRequest } from "@/src/shared/api/client";
import type { Company, CompanyCreate, FnsLookup } from "../model/types";

export const companyApi = {
  list: () => apiRequest<Company[]>("/companies"),
  create: (input: CompanyCreate) => apiRequest<Company>("/companies", { method: "POST", body: JSON.stringify(input) }),
  lookupInn: (inn: string, signal?: AbortSignal) => apiRequest<FnsLookup>(`/fns/lookup?inn=${encodeURIComponent(inn)}`, { signal }),
};
