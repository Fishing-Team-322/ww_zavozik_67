export type LegalForm = "ООО" | "ИП";
export type TaxRegime = "usn6" | "usn15" | "osno" | "eshn" | "unknown";

export interface Company {
  id: string;
  name: string;
  inn: string | null;
  legal_form: LegalForm;
  industry: string;
  tax_regime: TaxRegime;
  reserve: number;
  default_horizon: 30 | 60 | 90;
  data_as_of: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompanyCreate {
  name: string;
  inn: string | null;
  legal_form: LegalForm;
  industry: string;
  tax_regime: TaxRegime;
  reserve: number;
}

export interface FnsLookup {
  inn?: string;
  name?: string;
  legal_form?: string | null;
  industry?: string | null;
  tax_regime?: string;
  status?: string;
  source?: string;
}
