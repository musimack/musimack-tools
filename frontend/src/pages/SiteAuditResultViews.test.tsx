import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { siteAuditsApi } from '../site-audits/api';
import {
  ArtifactsResult,
  EvidenceResult,
  ExclusionsResult,
  SettingsSnapshotResult,
  SitemapResult,
} from './SiteAuditResultViews';

vi.mock('../site-audits/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../site-audits/api')>();
  return { ...original, siteAuditsApi: { ...original.siteAuditsApi, projection: vi.fn() } };
});

const projection = vi.mocked(siteAuditsApi.projection);
const page = (items: Record<string, unknown>[]) => ({
  items,
  offset: 0,
  page_size: 50,
  total: items.length,
  ordering: 'stable',
});

beforeEach(() => projection.mockReset());

test('renders product-facing sitemap documents and comparisons with route filters', async () => {
  projection.mockImplementation((_audit, resource) =>
    Promise.resolve(
      resource === 'sitemap-documents'
        ? page([
            {
              document_id: 'doc-1',
              requested_url: 'https://example.com/sitemap.xml',
              root_type: 'urlset',
              parse_state: 'parsed',
              entry_count: 10,
            },
          ])
        : {
            ...page([
              {
                url_id: 'url-1',
                sequence: 1,
                url: 'https://example.com/',
                comparison_state: 'valid_unchanged',
              },
            ]),
            existing_sitemap_module: { lifecycle: 'completed', completeness: 'complete' },
            comparison_totals: { include: 1, exclude: 0, review: 0, indeterminate: 0 },
            sitemap_totals: {
              index_count: 1,
              document_count: 7,
              entry_count: 103,
              sitemap_only_count: 96,
              fetch_failure_count: 0,
              definition: 'Present in an existing sitemap and not fetched by the parent crawl.',
            },
          },
    ),
  );
  render(
    <MemoryRouter>
      <SitemapResult auditId="audit-1" />
    </MemoryRouter>,
  );
  expect(await screen.findByText('Existing sitemap documents')).toBeVisible();
  expect(screen.getByText('https://example.com/sitemap.xml')).toBeVisible();
  expect(screen.getByText('103')).toBeVisible();
  expect(screen.getByText('96')).toBeVisible();
  expect(screen.getByText(/Present in an existing sitemap/iu)).toBeVisible();
  await userEvent.type(screen.getByLabelText('URL contains'), 'page');
  await waitFor(() => {
    expect(projection).toHaveBeenLastCalledWith(
      'audit-1',
      'sitemap-documents',
      0,
      50,
      expect.objectContaining({ url: 'page' }),
    );
  });
});

test('renders distinct governance decisions and bounded rule evidence', async () => {
  projection.mockResolvedValue(
    page([
      {
        url_id: 'url-1',
        original_url: 'https://example.com/?utm=x',
        normalized_url: 'https://example.com/',
        discovery_decision: 'enqueue',
        metadata_scoring_decision: 'exclude_from_metadata_scoring',
        sitemap_policy_decision: 'exclude_from_sitemap',
        rule_matches: [
          {
            snapshot_rule_id: 'rule-1',
            decision_layer: 'sitemap',
            primary_rule: true,
            reason: 'Excluded by governance',
          },
        ],
      },
    ]),
  );
  render(
    <MemoryRouter>
      <ExclusionsResult auditId="audit-1" />
    </MemoryRouter>,
  );
  expect(await screen.findByText('URL governance decisions')).toBeVisible();
  expect(screen.getAllByText(/exclude from metadata scoring/iu)).not.toHaveLength(0);
  expect(screen.getByText('Excluded by governance')).toBeVisible();
});

test('evidence is structured and never renders retained response bodies', async () => {
  projection.mockResolvedValue({
    audit: { lifecycle: 'completed' },
    orchestration: { current_stage: 'summary' },
    stages: [],
    modules: [],
    specialists: [],
    findings: [
      {
        finding_id: 'finding-1',
        module: 'metadata',
        code: 'missing_title',
        severity: 'high',
        explanation: 'Title is absent.',
        response_body: '<secret>',
      },
    ],
    body_content_retained: false,
    projection_version: 'v1',
    snapshot: {
      configuration: {
        operation_mode: 'real_site',
        submitted_by: 'operator',
        global_settings_version: 4,
        global_settings_hash: 'settings-hash',
        outbound_policy_version: 'policy-v1',
        crawler_user_agent: 'MusimackSeoToolkit/1.0',
        dns_timeout_seconds: 5,
        publication_enabled: false,
        external_ai_enabled: false,
        real_site_authorization: {
          status: 'enabled',
          authorized_by: 'administrator',
          global_settings_version: 4,
        },
        crawl_limits: {
          maximum_urls: 25,
          maximum_depth: 2,
          maximum_duration_seconds: 120,
          maximum_accepted_bytes: 40000000,
          maximum_concurrency: 1,
          maximum_queue_size: 100,
          minimum_request_delay_seconds: 1,
          maximum_redirect_hops: 5,
          maximum_response_bytes: 3000000,
        },
      },
    },
    operational_accounting: {
      crawl_elapsed_seconds: 10.25,
      request_count: 33,
      accepted_byte_count: 424360,
      redirect_count: 2,
      rejected_destination_count: 0,
      scope_denial_count: 9,
      robots_request_count: 2,
      sitemap_request_count: 7,
      retry_count: 0,
      timeout_count: 0,
      resolved_address_fingerprints: ['fingerprint'],
      robots_outcomes: { success: 2 },
      sitemap_outcomes: { success: 7 },
      url_admission: { admitted: 25, fetched: 25, over_limit: 1 },
    },
  });
  render(
    <MemoryRouter>
      <EvidenceResult auditId="audit-1" />
    </MemoryRouter>,
  );
  expect(await screen.findByText('Title is absent.')).toBeVisible();
  expect(screen.queryByText('<secret>')).not.toBeInTheDocument();
  expect(screen.getByText(/Raw HTML, response bodies/iu)).toBeVisible();
  expect(screen.getByText('administrator')).toBeVisible();
  expect(screen.getByText('MusimackSeoToolkit/1.0')).toBeVisible();
  expect(screen.getByText('424360')).toBeVisible();
  expect(screen.getByText('fingerprint')).toBeVisible();
  expect(screen.getByText('10.3 seconds')).toBeVisible();
  expect(screen.queryByText(/1970/iu)).not.toBeInTheDocument();
});

test('settings snapshot is explicitly immutable and rules are bounded', async () => {
  projection.mockResolvedValue({
    audit_id: 'audit-1',
    snapshot_id: 'snapshot-1',
    sha256: 'a'.repeat(64),
    configuration: {
      operation_mode: 'real_site',
      normalized_seed_url: 'https://example.com/',
      submitted_by: 'operator',
      global_settings_version: 4,
      global_settings_hash: 'settings-hash',
      outbound_policy_version: 'policy-v1',
      crawler_user_agent: 'MusimackSeoToolkit/1.0',
      dns_timeout_seconds: 5,
      publication_enabled: false,
      external_ai_enabled: false,
      summary_writing_enabled: false,
      real_site_authorization: {
        status: 'enabled',
        authorized_by: 'administrator',
        global_settings_version: 4,
      },
      approved_hosts: ['example.com'],
      crawl_limits: {
        maximum_urls: 25,
        maximum_depth: 2,
        maximum_duration_seconds: 120,
        maximum_accepted_bytes: 40000000,
        maximum_concurrency: 1,
        maximum_queue_size: 100,
        minimum_request_delay_seconds: 1,
        maximum_redirect_hops: 5,
        maximum_response_bytes: 3000000,
      },
      resolution: { crawl_limit_overrides: { maximum_urls: 25 } },
      rules: [{ stable_rule_id: 'rule-1', source: 'site_profile', action: 'exclude_from_sitemap' }],
    },
    projection_version: 'v1',
  });
  render(
    <MemoryRouter>
      <SettingsSnapshotResult auditId="audit-1" />
    </MemoryRouter>,
  );
  expect(await screen.findByText(/snapshot is immutable/iu)).toBeVisible();
  expect(screen.getByText('Effective rules')).toBeVisible();
  expect(screen.getByText('administrator')).toBeVisible();
  expect(screen.getByText('settings-hash')).toBeVisible();
  expect(screen.getByText('MusimackSeoToolkit/1.0')).toBeVisible();
  expect(screen.getByText('maximum urls: 25')).toBeVisible();
  expect(screen.queryByRole('button', { name: /edit/iu })).not.toBeInTheDocument();
});

test('artifact inventory exposes authenticated downloads without filesystem paths', async () => {
  projection.mockResolvedValue([
    {
      id: 1,
      artifact_id: 'artifact-1',
      purpose: 'recommended_sitemap_xml',
      schema_version: 'v1',
      completeness: 'complete',
      artifact: {
        filename: 'recommended-sitemap.xml',
        content_type: 'application/xml',
        byte_count: 120,
        sha256: 'b'.repeat(64),
        lifecycle_state: 'available',
        download_available: true,
        path_on_disk: 'C:\\secret',
      },
    },
  ]);
  render(
    <MemoryRouter>
      <ArtifactsResult auditId="audit-1" />
    </MemoryRouter>,
  );
  const download = await screen.findByRole('link', { name: 'Download Recommended sitemap XML' });
  expect(download).toHaveAttribute('href', '/api/internal/v1/artifacts/artifact-1/download');
  expect(screen.queryByText('C:\\secret')).not.toBeInTheDocument();
  expect(screen.getByText('recommended-sitemap.xml')).toBeVisible();
});
