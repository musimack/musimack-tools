import { jsonResponse } from '../test/fixtures';
import { defaultDraft } from './contracts';
import { safeHttpUrl, siteAuditsApi } from './api';

describe('combined Site Audit API', () => {
  test('uses private same-origin bounded history and result pagination', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(() =>
        Promise.resolve(jsonResponse({ data: { items: [], offset: 50, page_size: 50, total: 0 } })),
      );
    vi.stubGlobal('fetch', fetchMock);
    await siteAuditsApi.history({
      offset: 50,
      pageSize: 50,
      lifecycle: 'completed',
      search: 'Example site',
    });
    await siteAuditsApi.pages('audit-1', 50, 50);
    await siteAuditsApi.issues('audit-1', 100, 100);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/internal/v1/site-audits?offset=50&page_size=50&lifecycle=completed&search=Example+site',
      '/api/internal/v1/site-audits/audit-1/pages?offset=50&page_size=50',
      '/api/internal/v1/site-audits/audit-1/issues?offset=100&page_size=100',
    ]);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: 'include' });
  });

  test('serializes one durable draft boundary for save, validation, preflight, and submit', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(() =>
        Promise.resolve(jsonResponse({ data: { audit_id: 'audit-1', revision: 2 } })),
      );
    vi.stubGlobal('fetch', fetchMock);
    const draft = {
      ...defaultDraft(),
      audit_name: 'Fixture audit',
      seed_url: 'https://example.com/',
      crawl_limits: { maximum_urls: 50, maximum_accepted_bytes: 40_000_000 },
    };
    await siteAuditsApi.createDraft(draft, 'create-1');
    await siteAuditsApi.updateDraft('audit-1', 1, draft);
    await siteAuditsApi.validate('audit-1', 2);
    await siteAuditsApi.preflight('audit-1', 4);
    await siteAuditsApi.action('audit-1', 'submit');
    const firstRequest = fetchMock.mock.calls[0]?.[1];
    expect(firstRequest).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ draft }),
    });
    expect(new Headers(firstRequest?.headers).get('Idempotency-Key')).toBe('create-1');
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: 'PATCH',
      body: JSON.stringify({ revision: 1, draft }),
    });
    expect(fetchMock.mock.calls.slice(2).map(([url]) => url)).toEqual([
      '/api/internal/v1/site-audits/audit-1/validate',
      '/api/internal/v1/site-audits/audit-1/preflight',
      '/api/internal/v1/site-audits/audit-1/submit',
    ]);
  });

  test('rejects unsafe identifiers and external URL schemes', async () => {
    await expect(siteAuditsApi.detail('../unsafe')).rejects.toMatchObject({
      code: 'invalid_identifier',
    });
    expect(safeHttpUrl('https://example.com/page')).toBe('https://example.com/page');
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull();
    expect(safeHttpUrl('file:///etc/passwd')).toBeNull();
    expect(safeHttpUrl('not a URL')).toBeNull();
  });

  test('uses the private reconciliation action without request data', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(() => Promise.resolve(jsonResponse({ data: { lifecycle: 'queued' } })));
    vi.stubGlobal('fetch', fetchMock);
    await siteAuditsApi.action('audit-1', 'reconcile');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/site-audits/audit-1/reconcile',
      expect.objectContaining({ method: 'POST', body: '{}' }),
    );
  });

  test('serializes bounded result filters and private artifact downloads', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(() =>
        Promise.resolve(jsonResponse({ data: { items: [], offset: 0, page_size: 50, total: 0 } })),
      );
    vi.stubGlobal('fetch', fetchMock);
    await siteAuditsApi.pages('audit-1', 0, 50, {
      url: 'product',
      only_actionable: true,
      sort: 'severity',
      direction: 'desc',
    });
    await siteAuditsApi.issues('audit-1', 0, 50, {
      module: 'metadata',
      severity: 'high',
    });
    await siteAuditsApi.projection('audit-1', 'sitemap-documents', 50, 50, {
      parse_state: 'invalid',
    });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/internal/v1/site-audits/audit-1/pages?offset=0&page_size=50&url=product&only_actionable=true&sort=severity&direction=desc',
      '/api/internal/v1/site-audits/audit-1/issues?offset=0&page_size=50&module=metadata&severity=high',
      '/api/internal/v1/site-audits/audit-1/sitemap-documents?offset=50&page_size=50&parse_state=invalid',
    ]);
  });
});
