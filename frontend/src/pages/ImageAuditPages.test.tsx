import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach } from 'vitest';
import { imageAuditApi, type ImageAuditPage, type ImageAuditValue } from '../image-audits/api';
import {
  ImageAuditDashboardPage,
  ImageAuditExportsPage,
  ImageAuditInventoryPage,
  ImageAuditsPage,
  NewImageAuditPage,
} from './ImageAuditPages';

const auth = vi.hoisted(() => ({ allowed: true }));
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ can: () => auth.allowed }) }));

const page = (items: ImageAuditValue[]): ImageAuditPage => ({
  items,
  next_cursor: null,
  page_size: 50,
});

afterEach(() => {
  auth.allowed = true;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test('list renders durable audit metrics and hides mutations for viewers', async () => {
  vi.spyOn(imageAuditApi, 'list').mockResolvedValue(
    page([{ audit_id: 'audit-1', run_id: 'run-1', state: 'completed', broken_image_count: 2 }]),
  );
  const view = render(
    <MemoryRouter>
      <ImageAuditsPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'run-1' })).toHaveAttribute(
    'href',
    '/image-audits/audit-1',
  );
  view.unmount();
  auth.allowed = false;
  render(
    <MemoryRouter>
      <ImageAuditsPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'run-1' })).toBeVisible();
  expect(screen.queryByRole('link', { name: 'New image audit' })).not.toBeInTheDocument();
});

test('new audit checks backend evidence then executes and navigates', async () => {
  vi.spyOn(imageAuditApi, 'evidence').mockResolvedValue({
    compatible: true,
    page_evidence_count: 3,
    image_evidence_count: 7,
    scope_available: true,
  });
  vi.spyOn(imageAuditApi, 'create').mockResolvedValue({ audit_id: 'audit-1' });
  vi.spyOn(imageAuditApi, 'execute').mockResolvedValue({ state: 'completed' });
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/image-audits/new']}>
      <Routes>
        <Route path="/image-audits/new" element={<NewImageAuditPage />} />
        <Route path="/image-audits/:auditId" element={<h1>Audit dashboard</h1>} />
      </Routes>
    </MemoryRouter>,
  );
  await user.type(screen.getByLabelText('Completed crawl run ID'), 'run-1');
  await user.click(screen.getByRole('button', { name: 'Check evidence' }));
  expect(await screen.findByText(/image occurrences: 7/)).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Create and execute' }));
  expect(await screen.findByRole('heading', { name: 'Audit dashboard' })).toBeVisible();
  expect(imageAuditApi.execute).toHaveBeenCalledWith('audit-1');
});

test('new audit reports incompatible evidence and does not detach failed execution', async () => {
  vi.spyOn(imageAuditApi, 'evidence').mockResolvedValue({
    compatible: false,
    page_evidence_count: 3,
    image_evidence_count: 0,
    scope_available: false,
  });
  vi.spyOn(imageAuditApi, 'create').mockResolvedValue({ audit_id: 'audit-1' });
  vi.spyOn(imageAuditApi, 'execute').mockRejectedValue(new Error('conflict'));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/image-audits/new']}>
      <Routes>
        <Route path="/image-audits/new" element={<NewImageAuditPage />} />
        <Route path="/image-audits/:auditId" element={<h1>Audit dashboard</h1>} />
      </Routes>
    </MemoryRouter>,
  );
  await user.type(screen.getByLabelText('Completed crawl run ID'), 'run-old');
  expect(screen.getByText(/External images are not fetched by default/)).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Check evidence' }));
  expect(screen.getByRole('button', { name: 'Create and execute' })).toBeDisabled();

  vi.spyOn(imageAuditApi, 'evidence').mockResolvedValue({ compatible: true });
  await user.clear(screen.getByLabelText('Completed crawl run ID'));
  await user.type(screen.getByLabelText('Completed crawl run ID'), 'run-new');
  await user.click(screen.getByRole('button', { name: 'Check evidence' }));
  await user.click(screen.getByRole('button', { name: 'Create and execute' }));
  expect(await screen.findByText('The selected run is unavailable or incompatible.')).toBeVisible();
  expect(screen.queryByRole('heading', { name: 'Audit dashboard' })).not.toBeInTheDocument();
});

test('dashboard polls while nonterminal and stops when completed', async () => {
  vi.spyOn(window, 'setInterval').mockImplementation((callback) => {
    if (typeof callback === 'function') (callback as () => void)();
    return 1;
  });
  const summary = vi
    .spyOn(imageAuditApi, 'summary')
    .mockResolvedValueOnce({ state: 'resolving_resources' })
    .mockResolvedValue({ state: 'completed_with_warnings', image_occurrence_count: 7 });
  render(
    <MemoryRouter initialEntries={['/image-audits/audit-1']}>
      <Routes>
        <Route path="/image-audits/:auditId" element={<ImageAuditDashboardPage />} />
      </Routes>
    </MemoryRouter>,
  );
  await waitFor(() => {
    expect(summary).toHaveBeenCalledTimes(2);
  });
  expect(await screen.findByText('completed_with_warnings')).toBeVisible();
});

test.each([
  'resources',
  'occurrences',
  'broken',
  'redirecting',
  'alt-findings',
  'duplicate-groups',
  'pages',
  'dimensions',
  'loading',
  'recommendations',
])('%s view renders accessible evidence', async (resource) => {
  vi.spyOn(imageAuditApi, 'resource').mockResolvedValue(
    page([{ representative_url: 'https://example.com/image.png', severity: 'high' }]),
  );
  render(
    <MemoryRouter initialEntries={[`/image-audits/audit-1/${resource}`]}>
      <Routes>
        <Route path="/image-audits/:auditId/:resource" element={<ImageAuditInventoryPage />} />
      </Routes>
    </MemoryRouter>,
  );
  const table = await screen.findByRole('table');
  expect(table).toBeVisible();
  expect(within(table).getByText('high')).toBeVisible();
});

test('occurrence inventory submits search and alt filters and advances a filter-bound cursor', async () => {
  const resource = vi
    .spyOn(imageAuditApi, 'resource')
    .mockResolvedValueOnce(
      page([{ image_url: 'https://example.com/initial.png', severity: 'high' }]),
    )
    .mockResolvedValueOnce({
      items: [{ image_url: 'https://example.com/long.png', severity: 'high' }],
      next_cursor: 'next-1',
      page_size: 1,
    })
    .mockResolvedValue(page([{ image_url: 'https://example.com/next.png', severity: 'low' }]));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/image-audits/audit-1/occurrences']}>
      <Routes>
        <Route path="/image-audits/:auditId/:resource" element={<ImageAuditInventoryPage />} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByRole('table');
  await user.type(screen.getByLabelText('Search URL'), 'hero');
  await user.type(screen.getByLabelText('Search alt text'), 'product');
  await user.selectOptions(screen.getByLabelText('Severity'), 'high');
  await user.selectOptions(screen.getByLabelText('Alt state'), 'alt_missing');
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  await waitFor(() => {
    expect(resource).toHaveBeenCalledWith(
      'audit-1',
      'occurrences',
      expect.objectContaining({
        url: 'hero',
        alt: 'product',
        severity: 'high',
        alt_state: 'alt_missing',
        cursor: null,
      }),
    );
  });
  await user.click(screen.getByRole('button', { name: 'Next page' }));
  await waitFor(() => {
    expect(resource).toHaveBeenLastCalledWith(
      'audit-1',
      'occurrences',
      expect.objectContaining({ cursor: 'next-1' }),
    );
  });
});

test.each([
  ['resources', 'Resource state', 'broken_image', { resource_state: 'broken_image' }],
  ['recommendations', 'Confidence', 'medium', { confidence: 'medium' }],
] as const)(
  '%s inventory submits its specialized filter',
  async (view, label, option, expected) => {
    const resource = vi.spyOn(imageAuditApi, 'resource').mockResolvedValue(page([]));
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={[`/image-audits/audit-1/${view}`]}>
        <Routes>
          <Route path="/image-audits/:auditId/:resource" element={<ImageAuditInventoryPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByText('No matching evidence');
    await user.selectOptions(screen.getByLabelText(label), option);
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => {
      expect(resource).toHaveBeenLastCalledWith('audit-1', view, expect.objectContaining(expected));
    });
  },
);

test('resource-state filter exposes the complete backend taxonomy', async () => {
  vi.spyOn(imageAuditApi, 'resource').mockResolvedValue(page([]));
  render(
    <MemoryRouter initialEntries={['/image-audits/audit-1/resources']}>
      <Routes>
        <Route path="/image-audits/:auditId/:resource" element={<ImageAuditInventoryPage />} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByText('No matching evidence');
  for (const state of [
    'valid_image',
    'broken_image',
    'redirecting_image',
    'unverified_image',
    'external_image',
    'out_of_scope_image',
    'data_image',
    'placeholder_image',
    'unsupported_image_source',
  ]) {
    expect(screen.getByRole('option', { name: state })).toBeInTheDocument();
  }
});

test.each(['completed', 'failed', 'cancelled'])(
  'dashboard terminal state %s does not start polling',
  async (terminalState) => {
    const timer = vi.spyOn(window, 'setInterval');
    vi.spyOn(imageAuditApi, 'summary').mockResolvedValue({ state: terminalState });
    render(
      <MemoryRouter initialEntries={['/image-audits/audit-1']}>
        <Routes>
          <Route path="/image-audits/:auditId" element={<ImageAuditDashboardPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(terminalState)).toBeVisible();
    expect(timer).not.toHaveBeenCalledWith(expect.any(Function), 1_000);
  },
);

test('exports create all formats and disable writes for viewers', async () => {
  vi.spyOn(imageAuditApi, 'exports').mockResolvedValue([
    { export_id: 'e1', export_format: 'json', artifact_id: 'a1' },
  ]);
  const create = vi.spyOn(imageAuditApi, 'export').mockResolvedValue({ export_id: 'e2' });
  const user = userEvent.setup();
  const view = render(
    <MemoryRouter initialEntries={['/image-audits/audit-1/exports']}>
      <Routes>
        <Route path="/image-audits/:auditId/exports" element={<ImageAuditExportsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'Download' })).toHaveAttribute(
    'href',
    '/artifacts/a1',
  );
  await user.click(screen.getByRole('button', { name: 'json' }));
  expect(create).toHaveBeenCalledWith('audit-1', 'json');
  for (const name of [
    'image inventory csv',
    'alt findings csv',
    'broken redirecting images csv',
    'duplicate groups csv',
    'page summaries csv',
    'recommendations csv',
    'markdown',
  ]) {
    await user.click(screen.getByRole('button', { name }));
  }
  expect(create).toHaveBeenCalledTimes(8);
  view.unmount();
  auth.allowed = false;
  render(
    <MemoryRouter initialEntries={['/image-audits/audit-1/exports']}>
      <Routes>
        <Route path="/image-audits/:auditId/exports" element={<ImageAuditExportsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('button', { name: 'json' })).toBeDisabled();
});
