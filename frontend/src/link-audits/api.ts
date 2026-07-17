import { ApiError, requestJson } from '../api/client';
import {
  linkActions,
  linkAuditStates,
  type EvidenceStatus,
  type LinkAudit,
  type LinkExportFormat,
  type LinkPage,
  type LinkTarget,
} from './contracts';

export type LinkValue = Record<string, unknown>;
export type LinkQuery = Record<string, string | number | boolean | null | undefined>;

const record = (value: unknown): LinkValue => {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ApiError(502, 'invalid_response', 'The link audit response is invalid.', null, []);
  return value as LinkValue;
};
const data = (value: unknown) => record(value).data;
const identifier = (value: string) => {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The identifier is invalid.', null, []);
  return encodeURIComponent(value);
};
const query = (values: LinkQuery) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
  });
  return params.size ? `?${params.toString()}` : '';
};
const post = async (path: string, value: unknown) =>
  data(await requestJson(path, { method: 'POST', body: JSON.stringify(value) }));
const audit = (value: unknown): LinkAudit => {
  const item = record(value);
  if (
    typeof item.audit_id !== 'string' ||
    typeof item.run_id !== 'string' ||
    typeof item.state !== 'string' ||
    !(linkAuditStates as readonly string[]).includes(item.state) ||
    typeof item.target_count !== 'number'
  )
    throw new ApiError(502, 'invalid_response', 'The link audit is invalid.', null, []);
  return item as LinkAudit;
};
const target = (value: unknown): LinkTarget => {
  const item = record(value);
  if (
    typeof item.target_id !== 'string' ||
    typeof item.target_url !== 'string' ||
    typeof item.action !== 'string' ||
    !(linkActions as readonly string[]).includes(item.action)
  )
    throw new ApiError(502, 'invalid_response', 'The link target is invalid.', null, []);
  return item as LinkTarget;
};
const page = <T>(value: unknown, parser: (item: unknown) => T): LinkPage<T> => {
  const item = record(value);
  if (!Array.isArray(item.items) || typeof item.page_size !== 'number')
    throw new ApiError(502, 'invalid_response', 'The link audit page is invalid.', null, []);
  return { ...item, items: item.items.map(parser) } as LinkPage<T>;
};
const resource = async (
  auditId: string,
  name: string,
  values: LinkQuery = {},
): Promise<LinkPage<LinkValue>> =>
  page(
    data(await requestJson(`/audits/links/${identifier(auditId)}/${name}${query(values)}`)),
    record,
  );

export const linkAuditApi = {
  evidence: async (runId: string): Promise<EvidenceStatus> =>
    record(
      data(await requestJson(`/audits/links/evidence/${identifier(runId)}`)),
    ) as EvidenceStatus,
  create: async (runId: string): Promise<LinkAudit> =>
    audit(await post('/audits/links', { run_id: runId })),
  execute: async (auditId: string): Promise<LinkAudit> =>
    audit(await post(`/audits/links/${identifier(auditId)}/execute`, {})),
  list: async (values: LinkQuery = {}): Promise<LinkPage<LinkAudit>> =>
    page(data(await requestJson(`/audits/links${query(values)}`)), audit),
  get: async (auditId: string): Promise<LinkAudit> =>
    audit(data(await requestJson(`/audits/links/${identifier(auditId)}`))),
  summary: async (auditId: string): Promise<LinkValue> =>
    record(data(await requestJson(`/audits/links/${identifier(auditId)}/summary`))),
  targets: async (auditId: string, values: LinkQuery = {}): Promise<LinkPage<LinkTarget>> =>
    page(
      data(await requestJson(`/audits/links/${identifier(auditId)}/targets${query(values)}`)),
      target,
    ),
  occurrences: async (auditId: string, values: LinkQuery = {}) =>
    resource(auditId, 'occurrences', values),
  chains: async (auditId: string, values: LinkQuery = {}) => resource(auditId, 'chains', values),
  loops: async (auditId: string, values: LinkQuery = {}) => resource(auditId, 'loops', values),
  findings: async (auditId: string, values: LinkQuery = {}) =>
    resource(auditId, 'findings', values),
  recommendations: async (auditId: string, values: LinkQuery = {}) =>
    resource(auditId, 'recommendations', values),
  exports: async (auditId: string): Promise<LinkValue[]> => {
    const value = record(data(await requestJson(`/audits/links/${identifier(auditId)}/exports`)));
    if (!Array.isArray(value.items))
      throw new ApiError(502, 'invalid_response', 'Link audit exports are invalid.', null, []);
    return value.items.map(record);
  },
  export: async (auditId: string, format: LinkExportFormat): Promise<LinkValue> =>
    record(await post(`/audits/links/${identifier(auditId)}/exports`, { format })),
};
