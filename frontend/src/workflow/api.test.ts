import { jsonResponse } from '../test/fixtures';
import { ApiError } from '../api/client';
import { downloadArtifact, serializeCrawlRequest, workflowApi } from './api';
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
  test('serializes the default form request to the backend contract', () => {
    const serialized = serializeCrawlRequest(request);
    expect(serialized).toEqual({
      ...request,
      overrides: {},
      existing_file_policy: 'fail_if_exists',
    });
    expect(Object.keys(serialized.overrides)).not.toEqual(
      expect.arrayContaining([
        'max_urls',
        'max_depth',
        'max_duration',
        'max_accepted_bytes',
        'max_concurrency',
        'max_queue',
        'min_delay',
        'max_redirect_hops',
        'max_response_bytes',
      ]),
    );
    expect(serialized.existing_file_policy).not.toBe('fail');
  });

  test('serializes every advanced override to its backend field', () => {
    expect(
      serializeCrawlRequest({
        ...request,
        overrides: {
          max_urls: 101,
          max_depth: 7,
          max_duration: 300,
          max_accepted_bytes: 9_000_000,
          max_concurrency: 3,
          max_queue: 250,
          min_delay: 1.25,
          max_redirect_hops: 4,
          max_response_bytes: 2_000_000,
        },
        existing_file_policy: 'overwrite',
      }),
    ).toMatchObject({
      overrides: {
        maximum_urls: 101,
        maximum_depth: 7,
        maximum_duration_seconds: 300,
        maximum_accepted_bytes: 9_000_000,
        maximum_concurrency: 3,
        maximum_queue_size: 250,
        minimum_request_delay_seconds: 1.25,
        maximum_redirect_hops: 4,
        maximum_response_bytes: 2_000_000,
      },
      existing_file_policy: 'overwrite',
    });
  });

  test('submits validation with the serialized request and cookie credentials', async () => {
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
        body: JSON.stringify(serializeCrawlRequest(request)),
      }),
    );
  });

  test('submits preflight with the shared serializer', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        data: { state: 'ready', validation: {}, findings: [] },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await expect(workflowApi.preflight(request)).resolves.toMatchObject({ state: 'ready' });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/requests/preflight',
      expect.objectContaining({ body: JSON.stringify(serializeCrawlRequest(request)) }),
    );
  });

  test('submits crawl creation with the shared serializer', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        data: {
          outcome: 'accepted',
          status: {
            outcome: 'found',
            state: 'accepted',
            urls_discovered: 0,
            urls_fetched: 0,
            terminal: false,
            result_available: false,
          },
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await expect(workflowApi.submit(request)).resolves.toMatchObject({ outcome: 'accepted' });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/jobs',
      expect.objectContaining({ body: JSON.stringify(serializeCrawlRequest(request)) }),
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
      offset: 25,
      limit: 25,
      text: 'guide & news',
      state: 'include',
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/jobs/job-safe_1/recommendations?offset=25&limit=25&text=guide+%26+news&state=include',
      expect.anything(),
    );
  });

  test('loads a stable recommendation detail by durable sequence', async () => {
    const payload = {
      recommendation: {
        sequence: 5,
        url: 'https://example.test/noindex',
        state: 'exclude',
      },
      reason_codes: ['generic_noindex'],
      rule_evidence: [],
      warning_details: [],
      redirect_chain: [],
    };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ data: payload }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(workflowApi.recommendation('job-safe_1', 5)).resolves.toMatchObject(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/jobs/job-safe_1/recommendations/5',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  test.each([0, -1, 50_001, 1.5])(
    'rejects unsafe recommendation sequence %s before any network request',
    async (sequence) => {
      const fetchMock = vi.fn<typeof fetch>();
      vi.stubGlobal('fetch', fetchMock);
      await expect(workflowApi.recommendation('job-safe_1', sequence)).rejects.toBeInstanceOf(
        ApiError,
      );
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

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
