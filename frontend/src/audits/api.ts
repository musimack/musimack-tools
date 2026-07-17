import { ApiError, requestJson } from '../api/client';
import {
  auditStates,
  categories,
  issueCodes,
  severities,
  type Audit,
  type AuditIssue,
  type AuditPage,
  type DuplicateGroup,
  type ExportFormat,
  type Page,
} from './contracts';

type RecordValue = Record<string, unknown>;
type Query = Record<string, string | number | boolean | null | undefined>;
const record = (value: unknown): RecordValue => {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ApiError(
      502,
      'invalid_response',
      'The audit service returned an invalid response.',
      null,
      [],
    );
  return value as RecordValue;
};
const data = (value: unknown): unknown => record(value).data;
const id = (value: string): string => {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The identifier is invalid.', null, []);
  return encodeURIComponent(value);
};
const query = (values: Query): string => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
  });
  const result = params.toString();
  return result ? `?${result}` : '';
};
function audit(value: unknown): Audit {
  const item = record(value);
  if (
    typeof item.audit_id !== 'string' ||
    typeof item.run_id !== 'string' ||
    typeof item.state !== 'string' ||
    !(auditStates as readonly string[]).includes(item.state) ||
    typeof item.page_count !== 'number' ||
    typeof item.issue_count !== 'number'
  )
    throw new ApiError(502, 'invalid_response', 'The service returned an invalid audit.', null, []);
  return item as Audit;
}
function page<T>(value: unknown, parse: (item: unknown) => T): Page<T> {
  const result = record(value);
  if (
    !Array.isArray(result.items) ||
    typeof result.page_size !== 'number' ||
    typeof result.returned_count !== 'number' ||
    typeof result.ordering !== 'string'
  )
    throw new ApiError(
      502,
      'invalid_response',
      'The service returned an invalid audit page.',
      null,
      [],
    );
  return { ...result, items: result.items.map(parse) } as Page<T>;
}
const auditPage = (value: unknown): AuditPage => {
  const item = record(value);
  if (
    typeof item.audit_page_id !== 'string' ||
    typeof item.url !== 'string' ||
    typeof item.issue_count !== 'number'
  )
    throw new ApiError(502, 'invalid_response', 'Invalid page evidence.', null, []);
  return item as AuditPage;
};
const issue = (value: unknown): AuditIssue => {
  const item = record(value);
  if (
    typeof item.issue_id !== 'string' ||
    typeof item.code !== 'string' ||
    !(issueCodes as readonly string[]).includes(item.code) ||
    typeof item.category !== 'string' ||
    !(categories as readonly string[]).includes(item.category) ||
    typeof item.severity !== 'string' ||
    !(severities as readonly string[]).includes(item.severity)
  )
    throw new ApiError(502, 'invalid_response', 'Invalid audit issue.', null, []);
  return item as AuditIssue;
};
const group = (value: unknown): DuplicateGroup => {
  const item = record(value);
  if (
    typeof item.group_id !== 'string' ||
    typeof item.member_count !== 'number' ||
    !['title', 'meta_description'].includes(String(item.duplicate_type))
  )
    throw new ApiError(502, 'invalid_response', 'Invalid duplicate group.', null, []);
  return item as DuplicateGroup;
};
async function post(path: string, body: unknown): Promise<unknown> {
  return data(await requestJson(path, { method: 'POST', body: JSON.stringify(body) }));
}
export const auditApi = {
  create: async (runId: string): Promise<Audit> =>
    audit(await post('/audits/metadata', { run_id: runId })),
  list: async (values: Query = {}): Promise<Page<Audit>> =>
    page(data(await requestJson(`/audits/metadata${query(values)}`)), audit),
  get: async (auditId: string): Promise<Audit> =>
    audit(data(await requestJson(`/audits/metadata/${id(auditId)}`))),
  summary: async (auditId: string): Promise<RecordValue> =>
    record(data(await requestJson(`/audits/metadata/${id(auditId)}/summary`))),
  pages: async (auditId: string, values: Query = {}): Promise<Page<AuditPage>> =>
    page(
      data(await requestJson(`/audits/metadata/${id(auditId)}/pages${query(values)}`)),
      auditPage,
    ),
  page: async (auditId: string, pageId: string): Promise<RecordValue> =>
    record(data(await requestJson(`/audits/metadata/${id(auditId)}/pages/${id(pageId)}`))),
  issues: async (auditId: string, values: Query = {}): Promise<Page<AuditIssue>> =>
    page(data(await requestJson(`/audits/metadata/${id(auditId)}/issues${query(values)}`)), issue),
  duplicates: async (auditId: string, values: Query = {}): Promise<Page<DuplicateGroup>> =>
    page(
      data(await requestJson(`/audits/metadata/${id(auditId)}/duplicates${query(values)}`)),
      group,
    ),
  duplicate: async (auditId: string, groupId: string, values: Query = {}): Promise<RecordValue> =>
    record(
      data(
        await requestJson(
          `/audits/metadata/${id(auditId)}/duplicates/${id(groupId)}${query(values)}`,
        ),
      ),
    ),
  export: async (auditId: string, format: ExportFormat): Promise<RecordValue> =>
    record(await post(`/audits/metadata/${id(auditId)}/exports`, { format })),
};
