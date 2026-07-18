import { ApiError, requestJson } from '../api/client';

export type ImageAuditValue = Record<string, unknown>;
export type ImageAuditPage = {
  items: ImageAuditValue[];
  next_cursor: string | null;
  page_size: number;
};

const record = (value: unknown): ImageAuditValue => {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ApiError(502, 'invalid_response', 'The image-audit response is invalid.', null, []);
  return value as ImageAuditValue;
};
const data = (value: unknown) => record(value).data;
const id = (value: string) => {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The identifier is invalid.', null, []);
  return encodeURIComponent(value);
};
const post = async (path: string, body: unknown) =>
  data(await requestJson(path, { method: 'POST', body: JSON.stringify(body) }));
const page = (value: unknown): ImageAuditPage => {
  const item = record(value);
  if (!Array.isArray(item.items) || typeof item.page_size !== 'number')
    throw new ApiError(502, 'invalid_response', 'The image-audit page is invalid.', null, []);
  return { ...item, items: item.items.map(record) } as ImageAuditPage;
};
const query = (values: Record<string, string | null>) => {
  const parameters = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value) parameters.set(key, value);
  });
  return parameters.size ? `?${parameters.toString()}` : '';
};

export const imageAuditApi = {
  evidence: async (runId: string) =>
    record(data(await requestJson(`/audits/images/evidence/${id(runId)}`))),
  create: async (runId: string) => record(await post('/audits/images', { run_id: runId })),
  execute: async (auditId: string) =>
    record(await post(`/audits/images/${id(auditId)}/execute`, {})),
  list: async () => page(data(await requestJson('/audits/images'))),
  get: async (auditId: string) => record(data(await requestJson(`/audits/images/${id(auditId)}`))),
  summary: async (auditId: string) =>
    record(data(await requestJson(`/audits/images/${id(auditId)}/summary`))),
  resource: async (auditId: string, name: string, values: Record<string, string | null> = {}) =>
    page(data(await requestJson(`/audits/images/${id(auditId)}/${name}${query(values)}`))),
  exports: async (auditId: string) => {
    const value = record(data(await requestJson(`/audits/images/${id(auditId)}/exports`)));
    return Array.isArray(value.items) ? value.items.map(record) : [];
  },
  export: async (auditId: string, format: string) =>
    record(await post(`/audits/images/${id(auditId)}/exports`, { format })),
};
