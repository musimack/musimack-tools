import { jsonResponse } from '../test/fixtures';
import { ApiError } from '../api/client';
import { downloadArtifact, workflowApi } from './api';
import type { CrawlRequest } from './contracts';

const request: CrawlRequest = {
  seed_url: 'https://example.test/',
  scope_profile: 'exact_host',
  approved_hosts: [],
  crawl_profile: 'quick_audit',
  overrides: {
    max_urls: null,
    max_depth: null,
    max_duration: null,
    max_accepted_bytes: null,
    max_concurrency: null,
    max_queue: null,
    min_delay: null,
    max_redirect_hops: null,
    max_response_bytes: null,
  },
  recommendation_profile: 'standard',
  recommendation_requested: true,
  xml_generation_requested: true,
  publication_requested: false,
  publication_dry_run: true,
  publication_root: null,
  existing_file_policy: 'fail',
  create_publication_directory: false,
  summary_writing_requested: false,
  summary_root: null,
  create_summary_directory: false,
  summary_dry_run: true,
  caller_label: 'test',
};

describe('workflow API contract', () => {
  test('submits validation with the bounded request and cookie credentials', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        jsonResponse({ data: { valid: true, issues: [], selected_profile: 'quick_audit' } }),
      );
    vi.stubGlobal('fetch', fetchMock);
    await expect(workflowApi.validate(request)).resolves.toMatchObject({ valid: true });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/requests/validate',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify(request),
      }),
    );
  });

  test('lists live jobs from the existing jobs resource', async () => {
    const payload = { items: [], truncated: false, maximum: 100 };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ data: payload }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(workflowApi.jobs()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/jobs',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  test('encodes bounded recommendation filters without fragments', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ data: { items: [], total: 0, has_more: false } }));
    vi.stubGlobal('fetch', fetchMock);
    await workflowApi.recommendations('job-safe_1', {
      limit: 25,
      text: 'guide & news',
      state: 'include',
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/jobs/job-safe_1/recommendations?limit=25&text=guide+%26+news&state=include',
      expect.anything(),
    );
  });

  test('rejects unsafe identifiers before any network request', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
    await expect(workflowApi.status('../secret')).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('downloads only after an explicit call and honors a safe server filename', async () => {
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    const createUrl = vi.fn(() => 'blob:safe');
    const revokeUrl = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeUrl });
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response('xml', {
          headers: { 'Content-Disposition': 'attachment; filename="sitemap.xml"' },
        }),
      ),
    );
    await downloadArtifact('artifact-1', 'fallback.xml');
    expect(click).toHaveBeenCalledOnce();
    expect(createUrl).toHaveBeenCalledOnce();
    expect(revokeUrl).toHaveBeenCalledWith('blob:safe');
  });
});
