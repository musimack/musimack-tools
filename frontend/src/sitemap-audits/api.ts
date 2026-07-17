import { ApiError, requestJson } from '../api/client';
import {
  actions,
  auditStates,
  type Comparison,
  type CreateValues,
  type ExportFormat,
  type Page,
  type SitemapAudit,
  type SitemapCandidate,
} from './contracts';

type Value = Record<string, unknown>;
type Query = Record<string, string | number | null | undefined>;

const record = (value: unknown): Value => {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ApiError(502, 'invalid_response', 'The sitemap audit response is invalid.', null, []);
  return value as Value;
};
const data = (value: unknown) => record(value).data;
const identifier = (value: string) => {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The identifier is invalid.', null, []);
  return encodeURIComponent(value);
};
const query = (values: Query) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
  });
  return params.size ? `?${params.toString()}` : '';
};
const audit = (value: unknown): SitemapAudit => {
  const item = record(value);
  if (
    typeof item.audit_id !== 'string' ||
    typeof item.run_id !== 'string' ||
    typeof item.state !== 'string' ||
    !(auditStates as readonly string[]).includes(item.state) ||
    typeof item.comparison_count !== 'number'
  )
    throw new ApiError(502, 'invalid_response', 'The sitemap audit is invalid.', null, []);
  return item as SitemapAudit;
};
const comparison = (value: unknown): Comparison => {
  const item = record(value);
  if (
    typeof item.comparison_id !== 'string' ||
    typeof item.url !== 'string' ||
    typeof item.action !== 'string' ||
    !(actions as readonly string[]).includes(item.action)
  )
    throw new ApiError(502, 'invalid_response', 'The comparison record is invalid.', null, []);
  return item as Comparison;
};
const page = <T>(value: unknown, parser: (item: unknown) => T): Page<T> => {
  const item = record(value);
  if (!Array.isArray(item.items) || typeof item.page_size !== 'number')
    throw new ApiError(502, 'invalid_response', 'The sitemap audit page is invalid.', null, []);
  return { ...item, items: item.items.map(parser) } as Page<T>;
};
const body = (values: CreateValues) => ({
  run_id: values.runId,
  explicit_sitemap_url:
    values.explicitSitemapUrl === '' ? null : (values.explicitSitemapUrl ?? null),
  discover_robots: values.discoverRobots,
  discover_common_locations: values.discoverCommonLocations,
});
const post = async (path: string, value: unknown) =>
  data(await requestJson(path, { method: 'POST', body: JSON.stringify(value) }));

export const sitemapAuditApi = {
  discover: async (
    values: CreateValues,
  ): Promise<{ candidates: SitemapCandidate[]; findings: Value[] }> => {
    const result = record(await post('/audits/sitemaps/discover', body(values)));
    if (!Array.isArray(result.candidates) || !Array.isArray(result.findings))
      throw new ApiError(502, 'invalid_response', 'Sitemap discovery is invalid.', null, []);
    return result as { candidates: SitemapCandidate[]; findings: Value[] };
  },
  create: async (values: CreateValues): Promise<SitemapAudit> =>
    audit(await post('/audits/sitemaps', body(values))),
  execute: async (auditId: string): Promise<SitemapAudit> =>
    audit(await post(`/audits/sitemaps/${identifier(auditId)}/execute`, {})),
  list: async (values: Query = {}): Promise<Page<SitemapAudit>> =>
    page(data(await requestJson(`/audits/sitemaps${query(values)}`)), audit),
  get: async (auditId: string): Promise<SitemapAudit> =>
    audit(data(await requestJson(`/audits/sitemaps/${identifier(auditId)}`))),
  summary: async (auditId: string): Promise<Value> =>
    record(data(await requestJson(`/audits/sitemaps/${identifier(auditId)}/summary`))),
  documents: async (auditId: string, values: Query = {}): Promise<Page<Value>> =>
    page(
      data(await requestJson(`/audits/sitemaps/${identifier(auditId)}/documents${query(values)}`)),
      record,
    ),
  entries: async (auditId: string, values: Query = {}): Promise<Page<Value>> =>
    page(
      data(await requestJson(`/audits/sitemaps/${identifier(auditId)}/entries${query(values)}`)),
      record,
    ),
  findings: async (auditId: string, values: Query = {}): Promise<Page<Value>> =>
    page(
      data(await requestJson(`/audits/sitemaps/${identifier(auditId)}/findings${query(values)}`)),
      record,
    ),
  comparisons: async (auditId: string, values: Query = {}): Promise<Page<Comparison>> =>
    page(
      data(
        await requestJson(`/audits/sitemaps/${identifier(auditId)}/comparisons${query(values)}`),
      ),
      comparison,
    ),
  exports: async (auditId: string): Promise<Value[]> => {
    const result = record(
      data(await requestJson(`/audits/sitemaps/${identifier(auditId)}/exports`)),
    );
    if (!Array.isArray(result.items))
      throw new ApiError(502, 'invalid_response', 'Export references are invalid.', null, []);
    return result.items.map(record);
  },
  export: async (auditId: string, format: ExportFormat): Promise<Value> =>
    record(await post(`/audits/sitemaps/${identifier(auditId)}/exports`, { format })),
};
