import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach } from 'vitest';
import { sitemapAuditApi } from '../sitemap-audits/api';
import type { Comparison, Page, SitemapAudit } from '../sitemap-audits/contracts';
import {
  NewSitemapAuditPage,
  SitemapAuditDashboardPage,
  SitemapAuditsPage,
  SitemapDocumentsPage,
  SitemapEntriesPage,
  SitemapFindingsPage,
} from './SitemapAuditPages';

const completed: SitemapAudit = {
  audit_id: 'sitemap-audit-qa',
  job_id: 'job-qa',
  run_id: 'run-qa',
  seed_url: 'https://example.com/',
  explicit_sitemap_url: 'https://example.com/sitemap.xml',
  state: 'completed',
  failure_code: null,
  warning_count: 1,
  document_count: 2,
  unique_url_count: 4,
  comparison_count: 4,
  add_count: 1,
  remove_count: 1,
  review_count: 1,
  unchanged_count: 1,
  created_at: '2026-07-17T00:00:00Z',
  completed_at: '2026-07-17T00:00:01Z',
};

const comparisons: Page<Comparison> = {
  items: (['add', 'remove', 'review', 'unchanged'] as const).map((action, index) => ({
    comparison_id: `comparison-${action}`,
    url: `https://example.com/${action}`,
    action,
    comparison_state: `state-${action}`,
    reason_code: `reason-${action}`,
    recommendation_state: action === 'review' ? null : 'include',
    http_status: index === 2 ? null : 200,
    content_type: 'text/html',
  })),
  page_size: 4,
  returned_count: 4,
  next_cursor: 'next-page',
  ordering: 'comparison-order-v1',
  filters: {},
};

const page = <T,>(items: T[]): Page<T> => ({
  items,
  page_size: 50,
  returned_count: items.length,
  next_cursor: null,
  ordering: 'fixture-order-v1',
  filters: {},
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test('creation exposes accessible discovery controls and the gzip limitation', () => {
  render(
    <MemoryRouter>
      <NewSitemapAuditPage />
    </MemoryRouter>,
  );
  expect(screen.getByLabelText('Completed crawl run ID')).toBeRequired();
  expect(screen.getByLabelText('Explicit sitemap URL (optional)')).toHaveAttribute('type', 'url');
  expect(screen.getByRole('checkbox', { name: /robots.txt Sitemap directives/i })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: /common sitemap locations/i })).toBeChecked();
  expect(screen.getByText(/Gzip sitemap decompression is not supported/i)).toBeInTheDocument();
  expect(screen.getByText('Start sitemap audit')).toBeDisabled();
});

test('execution starts without blocking navigation or waiting for its response', async () => {
  vi.spyOn(sitemapAuditApi, 'create').mockResolvedValue({ ...completed, state: 'accepted' });
  vi.spyOn(sitemapAuditApi, 'execute').mockReturnValue(new Promise(() => undefined));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/sitemap-audits/new']}>
      <Routes>
        <Route path="/sitemap-audits/new" element={<NewSitemapAuditPage />} />
        <Route path="/sitemap-audits/:auditId" element={<h1>Polling audit</h1>} />
      </Routes>
    </MemoryRouter>,
  );
  await user.type(screen.getByLabelText('Completed crawl run ID'), 'run-qa');
  await user.click(screen.getByRole('button', { name: 'Start sitemap audit' }));
  expect(await screen.findByRole('heading', { name: 'Polling audit' })).toBeInTheDocument();
  expect(sitemapAuditApi.execute).toHaveBeenCalledWith('sitemap-audit-qa');
});

test('list renders both the empty state and retained audit navigation', async () => {
  const list = vi.spyOn(sitemapAuditApi, 'list').mockResolvedValue(page([]));
  const view = render(
    <MemoryRouter>
      <SitemapAuditsPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('heading', { name: 'No sitemap audits' })).toBeInTheDocument();
  list.mockResolvedValue(page([completed]));
  view.unmount();
  render(
    <MemoryRouter>
      <SitemapAuditsPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'https://example.com/' })).toHaveAttribute(
    'href',
    '/sitemap-audits/sitemap-audit-qa',
  );
});

test('dashboard shows every action, filters, pagination, status, and exports', async () => {
  vi.spyOn(sitemapAuditApi, 'get').mockResolvedValue(completed);
  const comparisonRequest = vi.spyOn(sitemapAuditApi, 'comparisons').mockResolvedValue(comparisons);
  vi.spyOn(sitemapAuditApi, 'export').mockResolvedValue({ artifact_id: 'artifact-qa' });
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/sitemap-audits/sitemap-audit-qa']}>
      <Routes>
        <Route path="/sitemap-audits/:auditId" element={<SitemapAuditDashboardPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('table', { name: 'Sitemap comparison results' })).toBeVisible();
  for (const action of ['add', 'remove', 'review', 'unchanged']) {
    expect(screen.getByText(action, { selector: 'td' })).toBeInTheDocument();
  }
  expect(screen.getByText('4', { selector: 'strong' })).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText('Action'), 'remove');
  await waitFor(() => {
    expect(comparisonRequest).toHaveBeenLastCalledWith('sitemap-audit-qa', {
      action: 'remove',
    });
  });
  await user.click(screen.getByRole('button', { name: 'CSV' }));
  expect(await screen.findByText('CSV ready: artifact-qa.')).toBeInTheDocument();
  expect(screen.getByRole('navigation', { name: 'Pagination' })).toBeInTheDocument();
  expect(screen.getByRole('navigation', { name: 'Sitemap audit inventory' })).toBeInTheDocument();
});

test('artifact export errors remain bounded and preserve audit evidence', async () => {
  vi.spyOn(sitemapAuditApi, 'get').mockResolvedValue(completed);
  vi.spyOn(sitemapAuditApi, 'comparisons').mockResolvedValue(comparisons);
  vi.spyOn(sitemapAuditApi, 'export').mockRejectedValue(new Error('private artifact detail'));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/sitemap-audits/sitemap-audit-qa']}>
      <Routes>
        <Route path="/sitemap-audits/:auditId" element={<SitemapAuditDashboardPage />} />
      </Routes>
    </MemoryRouter>,
  );
  await user.click(await screen.findByRole('button', { name: 'JSON' }));
  expect(await screen.findByText('Export failed; audit evidence remains intact.')).toBeVisible();
  expect(screen.queryByText('private artifact detail')).not.toBeInTheDocument();
});

test.each([
  [
    SitemapDocumentsPage,
    'documents',
    'requested_url',
    { document_id: 'doc', requested_url: 'https://example.com/sitemap.xml' },
  ],
  [
    SitemapEntriesPage,
    'entries',
    'raw_location',
    { entry_id: 'entry', raw_location: 'https://example.com/' },
  ],
  [
    SitemapFindingsPage,
    'findings',
    'safe_message',
    { finding_id: 'finding', safe_message: 'Review this location' },
  ],
] as const)(
  'renders retained %s inventory with accessible table labels',
  async (Component, kind, column, item) => {
    vi.spyOn(sitemapAuditApi, kind).mockResolvedValue(page([item]));
    render(
      <MemoryRouter initialEntries={[`/sitemap-audits/sitemap-audit-qa/${kind}`]}>
        <Routes>
          <Route path="/sitemap-audits/:auditId/:kind" element={<Component />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('table', { name: `Sitemap audit ${kind}` })).toBeVisible();
    expect(screen.getByText(column.replaceAll('_', ' '))).toBeInTheDocument();
  },
);

test('terminal lifecycle stops polling', async () => {
  vi.useFakeTimers();
  const get = vi.spyOn(sitemapAuditApi, 'get').mockResolvedValue(completed);
  vi.spyOn(sitemapAuditApi, 'comparisons').mockResolvedValue(comparisons);
  render(
    <MemoryRouter initialEntries={['/sitemap-audits/sitemap-audit-qa']}>
      <Routes>
        <Route path="/sitemap-audits/:auditId" element={<SitemapAuditDashboardPage />} />
      </Routes>
    </MemoryRouter>,
  );
  await act(async () => Promise.resolve());
  await act(async () => vi.advanceTimersByTimeAsync(5_000));
  expect(get).toHaveBeenCalledTimes(1);
});
