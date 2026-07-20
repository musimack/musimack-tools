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
