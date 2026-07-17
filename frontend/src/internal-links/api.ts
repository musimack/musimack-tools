import { ApiError, requestJson } from '../api/client';

export type InternalLinkValue = Record<string, unknown>;
export type InternalLinkPage = {
  items: InternalLinkValue[];
  next_cursor: string | null;
  page_size: number;
  returned_count: number;
};

const record = (value: unknown): InternalLinkValue => {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ApiError(502, 'invalid_response', 'The internal-link response is invalid.', null, []);
  return value as InternalLinkValue;
};
const data = (value: unknown) => record(value).data;
const id = (value: string) => {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The identifier is invalid.', null, []);
  return encodeURIComponent(value);
};
const post = async (path: string, body: unknown) =>
  data(await requestJson(path, { method: 'POST', body: JSON.stringify(body) }));
const query = (values: Record<string, string | null>) => {
  const parameters = new URLSearchParams();
  Object.entries(values).forEach(([key, item]) => {
    if (item) parameters.set(key, item);
  });
  return parameters.size ? `?${parameters.toString()}` : '';
};
const page = (value: unknown): InternalLinkPage => {
  const item = record(value);
  if (!Array.isArray(item.items) || typeof item.page_size !== 'number')
    throw new ApiError(502, 'invalid_response', 'The internal-link page is invalid.', null, []);
  return { ...item, items: item.items.map(record) } as InternalLinkPage;
};

export const internalLinkApi = {
  evidence: async (runId: string) =>
    record(data(await requestJson(`/audits/internal-links/evidence/${id(runId)}`))),
  create: async (runId: string) => record(await post('/audits/internal-links', { run_id: runId })),
  execute: async (auditId: string) =>
    record(await post(`/audits/internal-links/${id(auditId)}/execute`, {})),
  list: async () => page(data(await requestJson('/audits/internal-links'))),
  get: async (auditId: string) =>
    record(data(await requestJson(`/audits/internal-links/${id(auditId)}`))),
  summary: async (auditId: string) =>
    record(data(await requestJson(`/audits/internal-links/${id(auditId)}/summary`))),
  resource: async (auditId: string, name: string, values: Record<string, string | null> = {}) =>
    page(data(await requestJson(`/audits/internal-links/${id(auditId)}/${name}${query(values)}`))),
  exports: async (auditId: string) => {
    const value = record(data(await requestJson(`/audits/internal-links/${id(auditId)}/exports`)));
    return Array.isArray(value.items) ? value.items.map(record) : [];
  },
  export: async (auditId: string, format: string) =>
    record(await post(`/audits/internal-links/${id(auditId)}/exports`, { format })),
};
