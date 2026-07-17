import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach } from 'vitest';
import { linkAuditApi } from '../link-audits/api';
import type { LinkAudit, LinkPage, LinkTarget } from '../link-audits/contracts';
import {
  LinkAuditDashboardPage,
  LinkAuditsPage,
  LinkTargetsPage,
  NewLinkAuditPage,
} from './LinkAuditPages';

const completed: LinkAudit = {
  audit_id: 'link-audit-qa',
  job_id: 'job-qa',
  run_id: 'run-qa',
  seed_url: 'https://example.com/',
  state: 'completed',
  failure_code: null,
  warning_count: 0,
  link_occurrence_count: 5,
  source_target_pair_count: 4,
  target_count: 4,
  working_target_count: 1,
  broken_target_count: 1,
  redirect_target_count: 1,
  unverified_target_count: 1,
  redirect_chain_count: 1,
  redirect_loop_count: 0,
  recommendation_count: 3,
  created_at: '2026-07-17T00:00:00Z',
  completed_at: '2026-07-17T00:00:01Z',
};

const page = <T,>(items: T[]): LinkPage<T> => ({
  items,
  page_size: 50,
  returned_count: items.length,
  next_cursor: null,
  ordering: 'fixture-v1',
  filters: {},
});

afterEach(() => vi.restoreAllMocks());

test('creation gates execution on compatible durable evidence', async () => {
  vi.spyOn(linkAuditApi, 'evidence').mockResolvedValue({
    run_id: 'run-qa',
    terminal: true,
    page_evidence_count: 4,
    link_evidence_count: 5,
    scope_available: true,
    compatible: true,
  });
  vi.spyOn(linkAuditApi, 'create').mockResolvedValue({ ...completed, state: 'accepted' });
  vi.spyOn(linkAuditApi, 'execute').mockResolvedValue(completed);
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/link-audits/new']}>
      <Routes>
        <Route path="/link-audits/new" element={<NewLinkAuditPage />} />
        <Route path="/link-audits/:auditId" element={<h1>Polling audit</h1>} />
      </Routes>
    </MemoryRouter>,
  );
  await user.type(screen.getByLabelText('Completed crawl run ID'), 'run-qa');
  expect(screen.getByRole('button', { name: 'Start link audit' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Check evidence' }));
  expect(await screen.findByText(/link occurrences: 5/i)).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Start link audit' }));
  expect(await screen.findByRole('heading', { name: 'Polling audit' })).toBeVisible();
});

test('list and terminal dashboard expose retained counts and navigation', async () => {
  vi.spyOn(linkAuditApi, 'list').mockResolvedValue(page([completed]));
  const view = render(
    <MemoryRouter>
      <LinkAuditsPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'https://example.com/' })).toHaveAttribute(
    'href',
    '/link-audits/link-audit-qa',
  );
  view.unmount();
  vi.spyOn(linkAuditApi, 'get').mockResolvedValue(completed);
  vi.spyOn(linkAuditApi, 'summary').mockResolvedValue({ target_count: 4 });
  render(
    <MemoryRouter initialEntries={['/link-audits/link-audit-qa']}>
      <Routes>
        <Route path="/link-audits/:auditId" element={<LinkAuditDashboardPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('navigation', { name: 'Link audit views' })).toBeVisible();
  expect(screen.getByText('Broken')).toBeInTheDocument();
});

test('target view applies searchable state severity and action filters', async () => {
  const target: LinkTarget = {
    target_id: 'target-1',
    target_url: 'https://example.com/missing',
    broken_state: 'broken_internal_link',
    redirect_state: 'no_redirect',
    primary_reason: 'target_404',
    http_status: 404,
    fetch_state: 'complete',
    content_type: 'text/html',
    severity: 'high',
    action: 'remove_link',
    confidence: 'high',
    final_target: null,
    redirect_hop_count: 0,
    unique_source_page_count: 2,
    total_occurrence_count: 3,
    sitewide_candidate: false,
  };
  const targets = vi.spyOn(linkAuditApi, 'targets').mockResolvedValue(page([target]));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/link-audits/link-audit-qa/targets']}>
      <Routes>
        <Route path="/link-audits/:auditId/targets" element={<LinkTargetsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('table', { name: 'Link target analysis' })).toBeVisible();
  await user.type(screen.getByLabelText('Target URL'), 'missing');
  await user.selectOptions(screen.getByLabelText('State'), 'broken_internal_link');
  await user.selectOptions(screen.getByLabelText('Severity'), 'high');
  await user.selectOptions(screen.getByLabelText('Action'), 'remove_link');
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  expect(targets).toHaveBeenLastCalledWith(
    'link-audit-qa',
    expect.objectContaining({
      url: 'missing',
      broken_state: 'broken_internal_link',
      severity: 'high',
      action: 'remove_link',
    }),
  );
});
