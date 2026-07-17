import { beforeEach, describe, expect, it, vi } from 'vitest';
import { auditApi } from './api';
import { issueCodes } from './contracts';

const response = (data: unknown, status = 200) =>
  new Response(
    JSON.stringify({ metadata_audit_api_version: 'seo-toolkit-metadata-audit-api-v1', data }),
    {
      status,
      headers: { 'content-type': 'application/json', 'x-request-id': 'audit-test' },
    },
  );
const audit = {
  audit_id: 'audit-abc',
  job_id: 'job-abc',
  run_id: 'run-abc',
  seed_url: 'https://example.com/',
  state: 'completed',
  created_at: '2026-07-16T00:00:00Z',
  completed_at: '2026-07-16T00:00:01Z',
  page_count: 2,
  issue_count: 1,
  partial: false,
  failure_code: null,
  export_available: true,
};

describe('metadata audit API', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  it('creates an audit with one non-retried mutation', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(audit));
    await expect(auditApi.create('run-abc')).resolves.toMatchObject({ audit_id: 'audit-abc' });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/internal/v1/audits/metadata');
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ method: 'POST', credentials: 'include' });
  });
  it('narrows exact audit states', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ ...audit, state: 'invented' }));
    await expect(auditApi.get('audit-abc')).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('lists bounded audits with cursors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        items: [audit],
        page_size: 50,
        returned_count: 1,
        next_cursor: 'opaque',
        ordering: 'created_at_desc_audit_id_desc-v1',
      }),
    );
    await expect(auditApi.list({ cursor: 'opaque' })).resolves.toMatchObject({ returned_count: 1 });
  });
  it('narrows exact issue codes, categories, and severity', async () => {
    const issue = {
      issue_id: 'issue-abc',
      audit_page_id: 'page-abc',
      code: 'title_missing',
      category: 'title',
      severity: 'medium',
      summary: 'Title missing',
      detail: 'Finding',
      determinacy: 'determinate',
      duplicate_group_id: null,
      url: 'https://example.com/',
      status: 200,
      content_type: 'html',
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        items: [issue],
        page_size: 50,
        returned_count: 1,
        next_cursor: null,
        ordering: 'issue-order',
      }),
    );
    await expect(auditApi.issues('audit-abc')).resolves.toMatchObject({ items: [issue] });
  });
  it('rejects unknown issue codes', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        items: [{ issue_id: 'issue-abc', code: 'unknown', category: 'title', severity: 'medium' }],
        page_size: 50,
        returned_count: 1,
        next_cursor: null,
        ordering: 'issue-order',
      }),
    );
    await expect(auditApi.issues('audit-abc')).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('creates each supported export without placing credentials in the URL', async () => {
    const fetch = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(response({ artifact_id: 'artifact-1' })));
    for (const format of ['csv', 'json', 'markdown'] as const)
      await auditApi.export('audit-abc', format);
    expect(fetch).toHaveBeenCalledTimes(3);
    for (const [url] of fetch.mock.calls) {
      const requestUrl = url instanceof Request ? url.url : url instanceof URL ? url.href : url;
      expect(requestUrl).not.toMatch(/token|password|bearer/iu);
    }
  });
  it('exposes the complete stable issue-code union', () => {
    expect(issueCodes).toHaveLength(43);
    expect(new Set(issueCodes).size).toBe(issueCodes.length);
  });
  it('rejects unsafe identifiers before fetch', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    await expect(auditApi.get('../secret')).rejects.toMatchObject({ code: 'invalid_identifier' });
    expect(fetch).not.toHaveBeenCalled();
  });
});
