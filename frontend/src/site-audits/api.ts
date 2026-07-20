import { ApiError, requestJson } from '../api/client';
import type {
  AuditDetail,
  AuditHistory,
  AuditPage,
  AuditRecord,
  IssueFilters,
  IssueRecord,
  PageFilters,
  SiteAuditDraft,
  UrlRecord,
} from './contracts';

const BASE = '/site-audits';

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ApiError(502, 'invalid_response', 'The Site Audit response is invalid.', null, []);
  return value as Record<string, unknown>;
}

function data(value: unknown): unknown {
  return record(value).data;
}

function identifier(value: string): string {
  if (!/^[A-Za-z0-9._-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The Site Audit identifier is invalid.', null, []);
  return encodeURIComponent(value);
}

function query(values: Record<string, string | number | boolean | null | undefined>): string {
  const parameters = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') parameters.set(key, String(value));
  });
  const rendered = parameters.toString();
  return rendered ? `?${rendered}` : '';
}

async function send(path: string, method: 'POST' | 'PATCH', body: unknown): Promise<unknown> {
  return data(await requestJson(path, { method, body: JSON.stringify(body) }));
}

export const siteAuditsApi = {
  history: async (values: {
    offset?: number;
    pageSize?: number;
    lifecycle?: string;
    search?: string;
  }) =>
    data(
      await requestJson(
        `${BASE}${query({
          offset: values.offset ?? 0,
          page_size: values.pageSize ?? 50,
          lifecycle: values.lifecycle,
          search: values.search,
        })}`,
      ),
    ) as AuditHistory,
  createDraft: async (draft: SiteAuditDraft, idempotencyKey: string) =>
    data(
      await requestJson(BASE, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ draft }),
      }),
    ) as AuditRecord,
  detail: async (auditId: string) =>
    data(await requestJson(`${BASE}/${identifier(auditId)}`)) as AuditDetail,
  updateDraft: async (auditId: string, revision: number, draft: SiteAuditDraft) =>
    (await send(`${BASE}/${identifier(auditId)}/draft`, 'PATCH', {
      revision,
      draft,
    })) as AuditRecord,
  validate: async (auditId: string, revision: number) =>
    (await send(`${BASE}/${identifier(auditId)}/validate`, 'POST', { revision })) as Record<
      string,
      unknown
    >,
  preflight: async (auditId: string, revision: number) =>
    (await send(`${BASE}/${identifier(auditId)}/preflight`, 'POST', { revision })) as Record<
      string,
      unknown
    >,
  action: async (
    auditId: string,
    action: 'submit' | 'cancel' | 'retry' | 'reconcile' | 'archive',
  ) =>
    (await send(`${BASE}/${identifier(auditId)}/${action}`, 'POST', {})) as Record<string, unknown>,
  status: async (auditId: string) =>
    data(await requestJson(`${BASE}/${identifier(auditId)}/status`)) as Record<string, unknown>,
  summary: async (auditId: string) =>
    data(await requestJson(`${BASE}/${identifier(auditId)}/summary`)) as Record<string, unknown>,
  pages: async (auditId: string, offset: number, pageSize: number, filters: PageFilters = {}) =>
    data(
      await requestJson(
        `${BASE}/${identifier(auditId)}/pages${query({ offset, page_size: pageSize, ...filters })}`,
      ),
    ) as AuditPage<UrlRecord>,
  page: async (auditId: string, sequence: number) =>
    data(
      await requestJson(`${BASE}/${identifier(auditId)}/pages/${String(sequence)}`),
    ) as UrlRecord,
  issues: async (auditId: string, offset: number, pageSize: number, filters: IssueFilters = {}) =>
    data(
      await requestJson(
        `${BASE}/${identifier(auditId)}/issues${query({ offset, page_size: pageSize, ...filters })}`,
      ),
    ) as AuditPage<IssueRecord>,
  issue: async (auditId: string, groupId: string, offset: number, pageSize: number) =>
    data(
      await requestJson(
        `${BASE}/${identifier(auditId)}/issues/${identifier(groupId)}${query({
          offset,
          page_size: pageSize,
        })}`,
      ),
    ) as Record<string, unknown>,
  projection: async (
    auditId: string,
    resource:
      | 'sitemap-comparisons'
      | 'sitemap-documents'
      | 'exclusions'
      | 'evidence'
      | 'snapshot'
      | 'artifacts',
    offset = 0,
    pageSize = 50,
    filters: Record<string, string | number | boolean | null | undefined> = {},
  ) =>
    data(
      await requestJson(
        `${BASE}/${identifier(auditId)}/${resource}${
          resource === 'sitemap-comparisons' ||
          resource === 'sitemap-documents' ||
          resource === 'exclusions'
            ? query({ offset, page_size: pageSize, ...filters })
            : ''
        }`,
      ),
    ),
};

export const artifactDownloadUrl = (artifactId: string): string =>
  `/api/internal/v1/artifacts/${identifier(artifactId)}/download`;

export const safeHttpUrl = (value: unknown): string | null => {
  if (typeof value !== 'string') return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null;
  }
};
