import { ApiError, requestJson } from '../api/client';

export type MigrationQaValue = Record<string, unknown>;
export type MigrationQaPage = {
  items: MigrationQaValue[];
  next_cursor: string | null;
  page_size: number;
  total: number;
};

const record = (value: unknown): MigrationQaValue => {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ApiError(502, 'invalid_response', 'The migration QA response is invalid.', null, []);
  return value as MigrationQaValue;
};
const data = (value: unknown) => record(value).data;
const id = (value: string) => {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The identifier is invalid.', null, []);
  return encodeURIComponent(value);
};
const resource = (value: string) => {
  if (
    !/^(sources|redirect-map|mappings|redirects|comparisons|findings|recommendations|sitewide)$/u.test(
      value,
    )
  )
    throw new ApiError(0, 'invalid_resource', 'The resource is invalid.', null, []);
  return value;
};
const post = async (path: string, body: unknown) =>
  data(await requestJson(path, { method: 'POST', body: JSON.stringify(body) }));
const query = (values: Record<string, string | number | boolean | null | undefined>) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
  });
  return params.size ? `?${params.toString()}` : '';
};
const page = (value: unknown): MigrationQaPage => {
  const item = record(value);
  if (!Array.isArray(item.items) || typeof item.page_size !== 'number')
    throw new ApiError(502, 'invalid_response', 'The migration QA page is invalid.', null, []);
  return { ...item, items: item.items.map(record) } as MigrationQaPage;
};

export const migrationQaApi = {
  evidence: async (runId: string) =>
    record(data(await requestJson(`/migrations/qa/evidence/${id(runId)}`))),
  list: async () => page(data(await requestJson('/migrations/qa'))),
  create: async (request: MigrationQaValue) => record(await post('/migrations/qa', request)),
  detail: async (projectId: string) =>
    record(data(await requestJson(`/migrations/qa/${id(projectId)}`))),
  ingestSources: async (projectId: string, content: string) =>
    record(await post(`/migrations/qa/${id(projectId)}/source-inventory`, { content })),
  ingestRedirects: async (projectId: string, content: string) =>
    record(await post(`/migrations/qa/${id(projectId)}/redirect-map`, { content })),
  preview: async (projectId: string, kind: 'source_inventory' | 'redirect_map', content: string) =>
    record(await post(`/migrations/qa/${id(projectId)}/preview`, { kind, content })),
  readiness: async (projectId: string) =>
    record(data(await requestJson(`/migrations/qa/${id(projectId)}/readiness`))),
  execute: async (projectId: string) =>
    record(await post(`/migrations/qa/${id(projectId)}/execute`, {})),
  cancel: async (projectId: string) =>
    record(await post(`/migrations/qa/${id(projectId)}/cancel`, {})),
  summary: async (projectId: string) =>
    record(data(await requestJson(`/migrations/qa/${id(projectId)}/summary`))),
  resource: async (
    projectId: string,
    name: string,
    filters: Record<string, string | number | boolean | null | undefined> = {},
  ) =>
    page(
      data(await requestJson(`/migrations/qa/${id(projectId)}/${resource(name)}${query(filters)}`)),
    ),
  exports: async (projectId: string) => {
    const value = record(data(await requestJson(`/migrations/qa/${id(projectId)}/exports`)));
    return Array.isArray(value.items) ? value.items.map(record) : [];
  },
  export: async (projectId: string, format: string) =>
    record(await post(`/migrations/qa/${id(projectId)}/exports`, { format })),
};
