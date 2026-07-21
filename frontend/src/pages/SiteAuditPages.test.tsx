import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { siteAuditSettingsApi } from '../site-audit-settings/api';
import { siteAuditsApi } from '../site-audits/api';
import { defaultDraft, type AuditRecord } from '../site-audits/contracts';
import {
  NewSiteAuditPage,
  SiteAuditHistoryPage,
  SiteAuditLifecyclePage,
  SiteAuditPageDetailPage,
  SiteAuditResultsPage,
} from './SiteAuditPages';

vi.mock('../auth/AuthContext', () => ({ useAuth: vi.fn() }));
vi.mock('../site-audit-settings/api', () => ({
  siteAuditSettingsApi: { presets: vi.fn(), profiles: vi.fn() },
}));
vi.mock('../site-audits/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../site-audits/api')>();
  return {
    ...original,
    siteAuditsApi: {
      history: vi.fn(),
      createDraft: vi.fn(),
      detail: vi.fn(),
      updateDraft: vi.fn(),
      validate: vi.fn(),
      preflight: vi.fn(),
      action: vi.fn(),
      status: vi.fn(),
      summary: vi.fn(),
      pages: vi.fn(),
      page: vi.fn(),
      issues: vi.fn(),
      issue: vi.fn(),
      projection: vi.fn(),
    },
  };
});

const api = vi.mocked(siteAuditsApi);
const settings = vi.mocked(siteAuditSettingsApi);
const auth = vi.mocked(useAuth);
const draft = {
  ...defaultDraft(),
  audit_name: 'Fixture Site Audit',
  seed_url: 'https://example.com/',
};
const audit: AuditRecord = {
  audit_id: 'audit-1',
  audit_name: draft.audit_name,
  site_label: 'Example',
  seed_url: draft.seed_url,
  normalized_seed_url: draft.seed_url,
  lifecycle: 'draft',
  revision: 1,
  partial: false,
  population_completeness: 'unavailable',
  module_completeness: 'unavailable',
  created_at: '2026-07-20T00:00:00Z',
  updated_at: '2026-07-20T00:00:00Z',
  completed_at: null,
  failure_code: null,
  failure_explanation: null,
  draft,
};

beforeEach(() => {
  auth.mockReturnValue({
    can: () => true,
  } as unknown as ReturnType<typeof useAuth>);
  settings.presets.mockResolvedValue([]);
  settings.profiles.mockResolvedValue({
    items: [],
    offset: 0,
    limit: 500,
    total: 0,
    ordering: 'stable',
  });
});

test('history is searchable, bounded, and hides mutation destinations from viewers', async () => {
  auth.mockReturnValue({ can: () => false } as unknown as ReturnType<typeof useAuth>);
  api.history.mockResolvedValue({
    items: [audit],
    offset: 0,
    page_size: 50,
    total: 1,
    ordering: 'stable',
  });
  render(
    <MemoryRouter>
      <SiteAuditHistoryPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'Fixture Site Audit' })).toBeVisible();
  expect(screen.getByRole('link', { name: 'Fixture Site Audit' })).toHaveAttribute(
    'href',
    '/site-audits/audit-1',
  );
  expect(screen.queryByRole('link', { name: 'New Site Audit' })).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Global Audit Settings' })).not.toBeInTheDocument();
  await userEvent.type(screen.getByLabelText('Search'), 'example');
  await waitFor(() => {
    expect(api.history).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: 'example', pageSize: 50 }),
    );
  });
});

test('wizard persists a draft, survives route context, and exposes all seven steps', async () => {
  api.createDraft.mockResolvedValue(audit);
  render(
    <MemoryRouter initialEntries={['/site-audits/new?step=1']}>
      <Routes>
        <Route path="/site-audits/new" element={<NewSiteAuditPage />} />
        <Route path="/site-audits/:auditId/edit" element={<div>Saved route</div>} />
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getAllByRole('listitem')).toHaveLength(7);
  await userEvent.type(screen.getByLabelText('Audit name'), 'Fixture Site Audit');
  await userEvent.type(screen.getByLabelText('Seed URL'), 'https://example.com/');
  await userEvent.click(screen.getByRole('button', { name: 'Save and continue' }));
  await waitFor(() => {
    expect(api.createDraft).toHaveBeenCalledWith(
      expect.objectContaining({ seed_url: 'https://example.com/' }),
      expect.any(String),
    );
  });
  expect(await screen.findByText('Saved route')).toBeVisible();
});

test('wizard exposes the production request-delay floor and reports failed validation', async () => {
  api.detail.mockResolvedValue({ audit, snapshot: null, orchestration: null });
  api.validate.mockResolvedValue({
    audit: {
      ...audit,
      lifecycle: 'validation_failed',
      revision: 3,
      failure_code: 'site_audit_validation_failed',
      failure_explanation: 'The draft has validation errors.',
    },
    validation: {
      valid: false,
      issues: [
        {
          code: 'override_below_minimum',
          field: 'minimum_request_delay_seconds',
          explanation: 'minimum_request_delay_seconds is outside the accepted application boundary',
        },
      ],
    },
  });
  render(
    <MemoryRouter initialEntries={['/site-audits/audit-1/edit?step=4']}>
      <Routes>
        <Route path="/site-audits/:auditId/edit" element={<NewSiteAuditPage />} />
      </Routes>
    </MemoryRouter>,
  );
  const delay = await screen.findByLabelText('Minimum request delay (seconds)');
  expect(delay).toHaveAttribute('min', '0.1');
  await userEvent.click(screen.getByRole('button', { name: '7 Review and Submit' }));
  await userEvent.click(screen.getByRole('button', { name: 'Validate' }));
  expect(
    await screen.findByText(
      'minimum_request_delay_seconds is outside the accepted application boundary',
    ),
  ).toBeVisible();
  expect(screen.getByRole('button', { name: 'Run preflight' })).toBeDisabled();
  expect(screen.queryByText('Validation completed.')).not.toBeInTheDocument();
});

test('review shows the resolved rule count, sources, disabled rules, and tracking behavior', async () => {
  api.detail.mockResolvedValue({
    audit: {
      ...audit,
      draft: {
        ...audit.draft,
        platform_preset_id: 'wordpress',
        platform_preset_version: 'wordpress-1',
        preset_accepted: true,
      },
    },
    snapshot: null,
    orchestration: null,
    effective_settings: {
      effective_rules: [
        {
          rule_id: 'wordpress.cdn_cgi',
          name: 'Exclude /cdn-cgi/ from discovery',
          source: 'preset',
          action: 'exclude_from_discovery',
        },
        {
          rule_id: 'audit.review',
          name: 'Review fixture path',
          source: 'per_audit',
          action: 'crawl_and_mark_for_review',
        },
      ],
      disabled_inherited_rules: [{ rule_id: 'wordpress.wp_json' }],
      tracking_parameters_accepted: true,
      tracking_parameters: ['utm_source'],
      real_site_operations: { status: 'enabled', enabled: true },
      outbound_policy_version: 'seo-toolkit-outbound-destination-policy-v1',
      normalized_seed_url: 'https://example.com/',
      submitted_by: 'operator',
      crawler_user_agent: 'MusimackSeoToolkit/1.0',
      dns_timeout_seconds: 5,
      external_ai_enabled: false,
      summary_writing_enabled: false,
      crawl_limits: {
        maximum_urls: 25,
        maximum_queue_size: 100,
        maximum_response_bytes: 3000000,
      },
      warnings: [],
    },
  });
  render(
    <MemoryRouter initialEntries={['/site-audits/audit-1/edit?step=7']}>
      <Routes>
        <Route path="/site-audits/:auditId/edit" element={<NewSiteAuditPage />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByText('Effective URL-governance rules')).toBeVisible();
  expect(screen.getByText('Exclude /cdn-cgi/ from discovery')).toBeVisible();
  expect(screen.getByText('{"preset":1,"per_audit":1}')).toBeVisible();
  expect(screen.getByText('["utm_source"]')).toBeVisible();
  expect(screen.getByText('enabled')).toBeVisible();
  expect(screen.getByText('seo-toolkit-outbound-destination-policy-v1')).toBeVisible();
  expect(screen.getByText('MusimackSeoToolkit/1.0')).toBeVisible();
  expect(screen.getByText('operator')).toBeVisible();
  expect(screen.getByText('3000000')).toBeVisible();
  const disabled = screen.getByText('Disabled inherited rules').parentElement;
  expect(disabled).not.toBeNull();
  expect(within(disabled!).getByText('1')).toBeVisible();
});

test('summary renders bounded metrics without a request loop or raw projection', async () => {
  api.detail.mockResolvedValue({
    audit: { ...audit, lifecycle: 'completed' },
    snapshot: {},
    orchestration: {},
  });
  api.summary.mockResolvedValue({
    urls_discovered: 132,
    urls_fetched: 131,
    html_urls: 128,
    metadata_scoring_eligible_urls: 125,
    partial_urls: 1,
    failed_urls: 1,
    indeterminate_urls: 7,
    recommendation_include: 30,
    recommendation_exclude: 18,
    recommendation_review: 2,
    recommendation_indeterminate: 0,
    high_issue_groups: 3,
    projection_version: 'site-audit-summary-v1',
    operational_accounting: {
      request_count: 33,
      accepted_byte_count: 424360,
      redirect_count: 2,
      rejected_destination_count: 0,
      scope_denial_count: 9,
      url_admission: {
        admitted: 25,
        fetched: 25,
        over_limit: 1,
        definition: 'Over-limit discoveries are retained; queued work continues.',
      },
    },
  });
  render(
    <MemoryRouter initialEntries={['/site-audits/audit-1/results/summary']}>
      <Routes>
        <Route path="/site-audits/:auditId/results/:tab" element={<SiteAuditResultsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText('132')).toBeVisible();
  expect(screen.getByText('131 fetched')).toBeVisible();
  expect(screen.getByText('30')).toBeVisible();
  expect(screen.getByText(/Over-limit discoveries are retained/iu)).toBeVisible();
  expect(screen.getByText('424360')).toBeVisible();
  await waitFor(() => {
    expect(api.summary).toHaveBeenCalledTimes(1);
  });
  expect(document.querySelector('pre.safe-projection')).not.toBeInTheDocument();
});

test('pages preserve bounded pagination context and open internal detail first', async () => {
  api.detail.mockResolvedValue({
    audit: { ...audit, lifecycle: 'completed' },
    snapshot: {},
    orchestration: {},
  });
  api.pages.mockResolvedValue({
    items: [
      {
        sequence: 1,
        url_id: 'url-1',
        requested_url: 'https://example.com/',
        normalized_url: 'https://example.com/',
        final_url: 'https://example.com/',
        http_status: 200,
        content_type: 'text/html',
        fetch_outcome: 'fetched',
        discovery_decision: 'enqueue',
        sitemap_policy_decision: 'include',
        partial: false,
      },
    ],
    offset: 0,
    page_size: 50,
    total: 51,
    ordering: 'stable',
  });
  render(
    <MemoryRouter initialEntries={['/site-audits/audit-1/results/pages']}>
      <Routes>
        <Route path="/site-audits/:auditId/results/:tab" element={<SiteAuditResultsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  const table = await screen.findByRole('table');
  expect(within(table).getByRole('link', { name: 'https://example.com/' })).toHaveAttribute(
    'href',
    expect.stringContaining('/results/pages/1?return='),
  );
  expect(screen.getByText('1–50 of 51')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => {
    expect(api.pages).toHaveBeenLastCalledWith('audit-1', 50, 50, expect.any(Object));
  });
});

test('URL detail uses a safe new-tab action and does not render response bodies', async () => {
  api.page.mockResolvedValue({
    sequence: 1,
    url_id: 'url-1',
    requested_url: 'https://example.com/',
    normalized_url: 'https://example.com/',
    final_url: 'https://example.com/final',
    http_status: 200,
    content_type: 'text/html',
    fetch_outcome: 'fetched',
    discovery_decision: 'enqueue',
    sitemap_policy_decision: 'include',
    partial: false,
    response_body: '<secret>',
  });
  render(
    <MemoryRouter initialEntries={['/site-audits/audit-1/results/pages/1']}>
      <Routes>
        <Route
          path="/site-audits/:auditId/results/pages/:sequence"
          element={<SiteAuditPageDetailPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  const action = await screen.findByRole('link', { name: 'Open crawled URL in new tab' });
  expect(action).toHaveAttribute('target', '_blank');
  expect(action).toHaveAttribute('rel', 'noopener noreferrer');
  expect(action).toHaveAttribute('href', 'https://example.com/final');
  expect(screen.queryByText('<secret>')).not.toBeInTheDocument();
  expect(screen.queryByText(/response body/iu)).not.toBeInTheDocument();
});

test('administrators can reconcile recovery-required audits from the lifecycle view', async () => {
  api.detail.mockResolvedValue({
    audit: { ...audit, lifecycle: 'recovery_required' },
    snapshot: {},
    orchestration: {},
  });
  api.status.mockResolvedValue({ lifecycle: 'recovery_required' });
  api.action.mockResolvedValue({ lifecycle: 'queued' });
  render(
    <MemoryRouter initialEntries={['/site-audits/audit-1']}>
      <Routes>
        <Route path="/site-audits/:auditId" element={<SiteAuditLifecyclePage />} />
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole('button', { name: 'Reconcile audit' }));
  await waitFor(() => {
    expect(api.action).toHaveBeenCalledWith('audit-1', 'reconcile');
  });
});
