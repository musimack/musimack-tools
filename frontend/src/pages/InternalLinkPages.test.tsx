import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach } from 'vitest';
import {
  internalLinkApi,
  type InternalLinkPage,
  type InternalLinkValue,
} from '../internal-links/api';
import {
  InternalLinkDashboardPage,
  InternalLinkExportsPage,
  InternalLinkInventoryPage,
  InternalLinksPage,
  NewInternalLinkPage,
} from './InternalLinkPages';

const auth = vi.hoisted(() => ({ allowed: true }));
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ can: () => auth.allowed }),
}));

const page = (items: InternalLinkValue[], next: string | null = null): InternalLinkPage => ({
  items,
  next_cursor: next,
  page_size: 50,
  returned_count: items.length,
});

afterEach(() => {
  auth.allowed = true;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test('audit list covers retained rows, empty state, errors, and viewer restrictions', async () => {
  const list = vi.spyOn(internalLinkApi, 'list').mockResolvedValue(page([]));
  const view = render(
    <MemoryRouter>
      <InternalLinksPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('heading', { name: 'No internal-link analyses' })).toBeVisible();
  view.unmount();
  list.mockResolvedValue(
    page([{ audit_id: 'audit-1', seed_url: 'https://example.com/', state: 'completed' }]),
  );
  const retained = render(
    <MemoryRouter>
      <InternalLinksPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'https://example.com/' })).toHaveAttribute(
    'href',
    '/internal-links/audit-1',
  );
  retained.unmount();

  auth.allowed = false;
  list.mockRejectedValue(new Error('expired'));
  render(
    <MemoryRouter>
      <InternalLinksPage />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole('heading', { name: 'Internal-link analysis unavailable' }),
  ).toBeVisible();
  expect(
    screen.queryByRole('link', { name: 'New internal-link analysis' }),
  ).not.toBeInTheDocument();
});

test('new audit checks compatibility and launches detached execution before navigation', async () => {
  vi.spyOn(internalLinkApi, 'evidence').mockResolvedValue({
    compatible: true,
    page_evidence_count: 6,
    link_evidence_count: 7,
    scope_compatible: true,
    seed_compatible: true,
  });
  vi.spyOn(internalLinkApi, 'create').mockResolvedValue({ audit_id: 'audit-1' });
  vi.spyOn(internalLinkApi, 'execute').mockReturnValue(new Promise(() => undefined));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/internal-links/new']}>
      <Routes>
        <Route path="/internal-links/new" element={<NewInternalLinkPage />} />
        <Route path="/internal-links/:auditId" element={<h1>Polling analysis</h1>} />
      </Routes>
    </MemoryRouter>,
  );
  await user.type(screen.getByLabelText('Completed crawl run ID'), 'run-1');
  expect(screen.getByRole('button', { name: 'Create and execute' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Check evidence' }));
  expect(await screen.findByText(/Pages: 6; links: 7/)).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Create and execute' }));
  expect(await screen.findByRole('heading', { name: 'Polling analysis' })).toBeVisible();
  expect(internalLinkApi.execute).toHaveBeenCalledWith('audit-1');
});

test('dashboard polls nonterminal audits and stops at completed with warnings', async () => {
  vi.spyOn(window, 'setInterval').mockImplementation((callback) => {
    if (typeof callback === 'function') (callback as () => void)();
    return 1;
  });
  const summary = vi
    .spyOn(internalLinkApi, 'summary')
    .mockResolvedValueOnce({ state: 'building_graph', eligible_page_count: 6 })
    .mockResolvedValue({
      state: 'completed_with_warnings',
      eligible_page_count: 6,
      warning_count: 1,
    });
  render(
    <MemoryRouter initialEntries={['/internal-links/audit-1']}>
      <Routes>
        <Route path="/internal-links/:auditId" element={<InternalLinkDashboardPage />} />
      </Routes>
    </MemoryRouter>,
  );
  await waitFor(() => {
    expect(summary).toHaveBeenCalledTimes(2);
  });
  expect(await screen.findByText('completed_with_warnings')).toBeVisible();
  expect(summary).toHaveBeenCalledTimes(2);
});

test.each([
  'pages',
  'edges',
  'orphans',
  'hubs',
  'authorities',
  'reachability',
  'findings',
  'anchors',
  'opportunities',
])('%s inventory renders durable rows', async (resource) => {
  vi.spyOn(internalLinkApi, 'resource').mockResolvedValue(
    page([{ [`${resource}_id`]: 'row-1', state: 'high', url: 'https://example.com/a' }], 'next'),
  );
  render(
    <MemoryRouter initialEntries={[`/internal-links/audit-1/${resource}`]}>
      <Routes>
        <Route path="/internal-links/:auditId/:resource" element={<InternalLinkInventoryPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('table', { name: resource })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Next page' })).toBeVisible();
});

test('inventory submits URL, state, severity, and confidence filters', async () => {
  const resource = vi.spyOn(internalLinkApi, 'resource').mockResolvedValue(page([]));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/internal-links/audit-1/opportunities']}>
      <Routes>
        <Route path="/internal-links/:auditId/:resource" element={<InternalLinkInventoryPage />} />
      </Routes>
    </MemoryRouter>,
  );
  await user.type(screen.getByLabelText('Search URL'), 'missing');
  await user.type(screen.getByLabelText('State'), 'review');
  await user.selectOptions(screen.getByLabelText('Severity'), 'high');
  await user.selectOptions(screen.getByLabelText('Confidence'), 'medium');
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  await waitFor(() => {
    expect(resource).toHaveBeenLastCalledWith(
      'audit-1',
      'opportunities',
      expect.objectContaining({
        url: 'missing',
        state: 'review',
        severity: 'high',
        confidence: 'medium',
      }),
    );
  });
});

test('exports show mutation feedback and disable creation for viewers', async () => {
  vi.spyOn(internalLinkApi, 'exports').mockResolvedValue([
    { export_id: 'export-1', export_format: 'json', artifact_id: 'artifact-1' },
  ]);
  const create = vi.spyOn(internalLinkApi, 'export').mockResolvedValue({ export_id: 'export-2' });
  const user = userEvent.setup();
  const view = render(
    <MemoryRouter initialEntries={['/internal-links/audit-1/exports']}>
      <Routes>
        <Route path="/internal-links/:auditId/exports" element={<InternalLinkExportsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText(/artifact-1/)).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'json' }));
  expect(await screen.findByText('json created.')).toBeVisible();
  expect(create).toHaveBeenCalledWith('audit-1', 'json');
  view.unmount();
  auth.allowed = false;
  render(
    <MemoryRouter initialEntries={['/internal-links/audit-1/exports']}>
      <Routes>
        <Route path="/internal-links/:auditId/exports" element={<InternalLinkExportsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('button', { name: 'json' })).toBeDisabled();
});
