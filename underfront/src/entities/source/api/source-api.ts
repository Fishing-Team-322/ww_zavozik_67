import { apiRequest } from "@/src/shared/api/client";
import type { CreateSourceInput, DataSource, ImportReport, Job, UploadNeedsMapping, UploadPreview } from "../model/types";

const companyPath = (companyId: string) => `/companies/${encodeURIComponent(companyId)}`;

export const sourceApi = {
  list: (companyId: string) => apiRequest<DataSource[]>(`${companyPath(companyId)}/sources`),
  create: (companyId: string, input: CreateSourceInput) => apiRequest<DataSource>(`${companyPath(companyId)}/sources`, { method: "POST", body: JSON.stringify(input) }),
  sync: (sourceId: string) => apiRequest<Job>(`/sources/${encodeURIComponent(sourceId)}/sync`, { method: "POST" }),
  test: (sourceId: string) => apiRequest<{ ok: boolean; message: string }>(`/sources/${encodeURIComponent(sourceId)}/test`, { method: "POST" }),
  upload: (companyId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return apiRequest<Job | UploadNeedsMapping>(`${companyPath(companyId)}/uploads`, { method: "POST", body });
  },
  preview: (uploadId: string) => apiRequest<UploadPreview>(`/uploads/${encodeURIComponent(uploadId)}/preview`),
  map: (uploadId: string, mapping: Record<string, string>) => apiRequest<Job>(`/uploads/${encodeURIComponent(uploadId)}/mapping`, { method: "POST", body: JSON.stringify({ mapping }) }),
  job: (jobId: string) => apiRequest<Job>(`/jobs/${encodeURIComponent(jobId)}`),
  imports: (companyId: string) => apiRequest<ImportReport[]>(`${companyPath(companyId)}/imports`),
  import: (importId: string) => apiRequest<ImportReport>(`/imports/${encodeURIComponent(importId)}`),
};
