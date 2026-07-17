import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sitemapAuditApi } from './api';

const response = (data: unknown) =>
  new Response(JSON.stringify({ sitemap_audit_api_version: 'v1', data }), {
    status: 200,
    headers: { 'content-type': 'application/json', 'x-request-id': 'sitemap-test' },
  });
const audit = {
  audit_id: 'sitemap-audit-abc',
  job_id: 'job-abc',
  run_id: 'run-abc',
  seed_url: 'https://example.com/',
  explicit_sitemap_url: 'https://example.com/sitemap.xml',
  state: 'completed',
  failure_code: null,
  warning_count: 0,
  document_count: 1,
  unique_url_count: 2,
  comparison_count: 2,
  add_count: 1,
  remove_count: 0,
  review_count: 0,
  unchanged_count: 1,
  created_at: '2026-07-16T00:00:00Z',
  completed_at: '2026-07-16T00:00:01Z',
};
const values = {
  runId: 'run-abc',
  explicitSitemapUrl: 'https://example.com/sitemap.xml',
  discoverRobots: true,
  discoverCommonLocations: true,
};

describe('sitemap audit API', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('previews deterministic discovery through the private namespace', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        candidates: [
          {
            normalized_url: 'https://example.com/sitemap.xml',
            discovery_source: 'explicit',
            discovery_sequence: 0,
            provenance: ['explicit'],
            raw_url: 'https://example.com/sitemap.xml',
          },
        ],
        findings: [],
      }),
    );
    await expect(sitemapAuditApi.discover(values)).resolves.toMatchObject({ candidates: [{}] });
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/internal/v1/audits/sitemaps/discover');
  });

  it('creates exactly one non-retried audit mutation', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(audit));
    await expect(sitemapAuditApi.create(values)).resolves.toMatchObject({
      audit_id: 'sitemap-audit-abc',
    });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ method: 'POST', credentials: 'include' });
  });

  it('executes an accepted audit through a separate explicit mutation', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(audit));
    await expect(sitemapAuditApi.execute('sitemap-audit-abc')).resolves.toMatchObject({
      state: 'completed',
    });
    expect(fetch.mock.calls[0]?.[0]).toBe(
      '/api/internal/v1/audits/sitemaps/sitemap-audit-abc/execute',
    );
  });

  it('rejects an uncontrolled lifecycle state', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ ...audit, state: 'invented' }));
    await expect(sitemapAuditApi.get('sitemap-audit-abc')).rejects.toMatchObject({
      code: 'invalid_response',
    });
  });

  it('lists comparisons with action, reason, URL, and cursor filters', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        items: [
          {
            comparison_id: 'comparison-1',
            url: 'https://example.com/',
            action: 'unchanged',
            comparison_state: 'in_sitemap_and_eligible',
            reason_code: 'eligible_already_present',
            recommendation_state: 'include',
            http_status: 200,
            content_type: 'text/html',
          },
        ],
        page_size: 50,
        returned_count: 1,
        next_cursor: null,
        ordering: 'comparison-order',
        filters: {},
      }),
    );
    await sitemapAuditApi.comparisons('sitemap-audit-abc', {
      action: 'unchanged',
      reason: 'eligible_already_present',
      url: 'example',
      cursor: 'opaque',
    });
    expect(fetch.mock.calls[0]?.[0]).toContain('action=unchanged');
    expect(fetch.mock.calls[0]?.[0]).toContain('cursor=opaque');
  });

  it('rejects an uncontrolled comparison action', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        items: [{ comparison_id: 'c', url: 'https://example.com/', action: 'delete' }],
        page_size: 50,
      }),
    );
    await expect(sitemapAuditApi.comparisons('sitemap-audit-abc')).rejects.toMatchObject({
      code: 'invalid_response',
    });
  });

  it('loads documents, entries, findings, and export references', async () => {
    const fetch = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() =>
        Promise.resolve(response({ items: [{ document_id: 'doc-1' }], page_size: 50 })),
      );
    await sitemapAuditApi.documents('sitemap-audit-abc');
    await sitemapAuditApi.entries('sitemap-audit-abc');
    await sitemapAuditApi.findings('sitemap-audit-abc');
    await sitemapAuditApi.exports('sitemap-audit-abc');
    expect(fetch).toHaveBeenCalledTimes(4);
  });

  it('creates all export formats without credentials in URLs', async () => {
    const fetch = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() =>
        Promise.resolve(response({ export_id: 'export-1', artifact_id: 'artifact-1' })),
      );
    for (const format of ['csv', 'json', 'markdown'] as const)
      await sitemapAuditApi.export('sitemap-audit-abc', format);
    for (const [url] of fetch.mock.calls) {
      const requestUrl = url instanceof Request ? url.url : url instanceof URL ? url.href : url;
      expect(requestUrl).not.toMatch(/token|password|bearer/iu);
    }
  });

  it('rejects unsafe identifiers before network access', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    await expect(sitemapAuditApi.get('../secret')).rejects.toMatchObject({
      code: 'invalid_identifier',
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('surfaces authentication expiration from every private read', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: 'authentication_required',
            message: 'Sign in again.',
            details: [],
          },
        }),
        { status: 401, headers: { 'content-type': 'application/json' } },
      ),
    );
    await expect(sitemapAuditApi.get('sitemap-audit-abc')).rejects.toMatchObject({ status: 401 });
  });
});
