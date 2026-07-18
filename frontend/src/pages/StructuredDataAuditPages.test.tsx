import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import {
  structuredDataAuditApi,
  type StructuredDataPage,
  type StructuredDataValue,
} from '../structured-data-audits/api';
import {
  NewStructuredDataAuditPage,
  StructuredDataAuditDashboardPage,
  StructuredDataAuditExportsPage,
  StructuredDataAuditInventoryPage,
  StructuredDataAuditsPage,
} from './StructuredDataAuditPages';

const auth = vi.hoisted(() => ({ allowed: true }));
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ can: () => auth.allowed }) }));
const page = (items: StructuredDataValue[]): StructuredDataPage => ({
  items,
  next_cursor: null,
  page_size: 50,
});

afterEach(() => {
  auth.allowed = true;
  vi.restoreAllMocks();
});

test('list exposes durable metrics and hides mutation navigation from viewers', async () => {
  vi.spyOn(structuredDataAuditApi, 'list').mockResolvedValue(
    page([{ audit_id: 'audit-1', run_id: 'run-1', state: 'completed', total_blocks: 4 }]),
  );
  const view = render(
    <MemoryRouter>
      <StructuredDataAuditsPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'run-1' })).toHaveAttribute(
    'href',
    '/structured-data-audits/audit-1',
  );
  view.unmount();
  auth.allowed = false;
  render(
    <MemoryRouter>
      <StructuredDataAuditsPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'run-1' })).toBeVisible();
  expect(
    screen.queryByRole('link', { name: /New structured-data audit/i }),
  ).not.toBeInTheDocument();
});

test('new audit checks retained evidence then executes and navigates', async () => {
  vi.spyOn(structuredDataAuditApi, 'evidence').mockResolvedValue({
    ready: true,
    page_count: 2,
    block_count: 4,
  });
  vi.spyOn(structuredDataAuditApi, 'create').mockResolvedValue({ audit_id: 'audit-1' });
  vi.spyOn(structuredDataAuditApi, 'execute').mockResolvedValue({ state: 'completed' });
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/new']}>
      <Routes>
        <Route path="/structured-data-audits/new" element={<NewStructuredDataAuditPage />} />
        <Route path="/structured-data-audits/:auditId" element={<h1>Audit dashboard</h1>} />
      </Routes>
    </MemoryRouter>,
  );
  await user.type(screen.getByLabelText('Completed crawl run ID'), 'run-1');
  await user.click(screen.getByRole('button', { name: 'Check evidence' }));
  expect(await screen.findByText(/blocks: 4/)).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Create and execute' }));
  expect(await screen.findByRole('heading', { name: 'Audit dashboard' })).toBeVisible();
});

test('summary states the non-certifying boundary', async () => {
  vi.spyOn(structuredDataAuditApi, 'summary').mockResolvedValue({
    state: 'completed',
    total_blocks: 4,
  });
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/audit-1']}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId"
          element={<StructuredDataAuditDashboardPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText(/does not certify search-engine eligibility/i)).toBeVisible();
});

test.each([
  'blocks',
  'entities',
  'properties',
  'pages',
  'parse-findings',
  'consistency-findings',
  'duplicate-groups',
  'profiles',
  'recommendations',
])('%s inventory renders bounded evidence', async (resource) => {
  vi.spyOn(structuredDataAuditApi, 'resource').mockResolvedValue(
    page([
      {
        id: 'row-1',
        page_url: 'https://example.test',
        code: 'json_ld_missing_type',
        explanation: 'Missing type',
      },
    ]),
  );
  render(
    <MemoryRouter initialEntries={[`/structured-data-audits/audit-1/${resource}`]}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId/:resource"
          element={<StructuredDataAuditInventoryPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('table')).toBeVisible();
  expect(screen.getByText('json_ld_missing_type')).toBeVisible();
});

test('all eight export actions are available', async () => {
  vi.spyOn(structuredDataAuditApi, 'exports').mockResolvedValue([]);
  vi.spyOn(structuredDataAuditApi, 'export').mockResolvedValue({ id: 'export-1' });
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/audit-1/exports']}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId/exports"
          element={<StructuredDataAuditExportsPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findAllByRole('button')).toHaveLength(8);
});

test('finding metadata is rendered with explicit review state', async () => {
  vi.spyOn(structuredDataAuditApi, 'resource').mockResolvedValue(
    page([
      {
        id: 'finding-1',
        page_url: 'https://example.test/a-very-long-path',
        code: 'entity_conflicting_types',
        explanation: 'Retained types conflict.',
        confidence: 'medium',
        requires_human_review: true,
      },
    ]),
  );
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/audit-1/consistency-findings']}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId/:resource"
          element={<StructuredDataAuditInventoryPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText('medium')).toBeVisible();
  expect(screen.getByText('true')).toBeVisible();
  expect(screen.getByText('https://example.test/a-very-long-path')).toHaveClass('wrap-anywhere');
});

test('recommendation scope counts and supporting metadata are rendered', async () => {
  vi.spyOn(structuredDataAuditApi, 'resource').mockResolvedValue(
    page([
      {
        id: 'recommendation-1',
        action: 'review_schema_format_mix',
        explanation: 'Review overlapping formats.',
        confidence: 'low',
        requires_human_review: true,
        scope: 'page',
        occurrence_count: 2,
        affected_page_count: 1,
        supporting_finding_ids_json: '[]',
        supporting_evidence_json: '{"page_ids":["page-1"]}',
      },
    ]),
  );
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/audit-1/recommendations']}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId/:resource"
          element={<StructuredDataAuditInventoryPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText('review_schema_format_mix')).toBeVisible();
  expect(screen.getByText(/page \/ 2 occurrences \/ 1 pages/)).toBeVisible();
});

test.each([
  'present',
  'missing',
  'empty',
  'invalid',
  'conflicting',
  'not_applicable',
  'indeterminate',
])('profile state %s is rendered without a certification claim', async (observationState) => {
  vi.spyOn(structuredDataAuditApi, 'resource').mockResolvedValue(
    page([
      {
        id: `profile-${observationState}`,
        entity_id: 'entity-1',
        profile_name: 'Organization',
        profile_version: 'seo-toolkit-structured-data-profiles-v1',
        observation_state: observationState,
      },
    ]),
  );
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/audit-1/profiles']}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId/:resource"
          element={<StructuredDataAuditInventoryPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText(observationState)).toBeVisible();
});

test('search and structured filters bind the resource query and reset pagination', async () => {
  const resource = vi
    .spyOn(structuredDataAuditApi, 'resource')
    .mockResolvedValue(page([{ id: 'row-1', format: 'json_ld' }]));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/audit-1/blocks']}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId/:resource"
          element={<StructuredDataAuditInventoryPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByRole('table');
  await user.type(screen.getByLabelText('Search retained evidence'), 'Organization');
  await user.selectOptions(screen.getByLabelText('Severity'), 'warning');
  await user.selectOptions(screen.getByLabelText('Confidence'), 'medium');
  await user.selectOptions(screen.getByLabelText('Profile state'), 'invalid');
  await user.selectOptions(screen.getByLabelText('Format'), 'json_ld');
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  expect(resource).toHaveBeenLastCalledWith(
    'audit-1',
    'blocks',
    expect.objectContaining({
      search: 'Organization',
      severity: 'warning',
      confidence: 'medium',
      observation_state: 'invalid',
      format: 'json_ld',
      cursor: null,
    }),
  );
});

test('cursor pagination requests the next stable page', async () => {
  const resource = vi.spyOn(structuredDataAuditApi, 'resource');
  resource
    .mockResolvedValueOnce({ items: [{ id: 'row-1' }], next_cursor: 'next-1', page_size: 20 })
    .mockResolvedValueOnce(page([{ id: 'row-2' }]));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/audit-1/blocks']}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId/:resource"
          element={<StructuredDataAuditInventoryPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  await user.click(await screen.findByRole('button', { name: 'Next page' }));
  expect(resource).toHaveBeenLastCalledWith(
    'audit-1',
    'blocks',
    expect.objectContaining({ cursor: 'next-1' }),
  );
});

test('viewers see artifact history and downloads but no export mutations', async () => {
  auth.allowed = false;
  vi.spyOn(structuredDataAuditApi, 'exports').mockResolvedValue([
    {
      id: 'export-1',
      artifact_id: 'artifact-1',
      export_format: 'json',
      filename: 'audit.json',
      media_type: 'application/json',
    },
  ]);
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/audit-1/exports']}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId/exports"
          element={<StructuredDataAuditExportsPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'audit.json' })).toHaveAttribute(
    'href',
    '/artifacts/artifact-1',
  );
  expect(screen.queryAllByRole('button')).toHaveLength(0);
  expect(screen.getByText(/Viewer access is read-only/)).toBeVisible();
});

test('export creation errors remain visible without removing history', async () => {
  vi.spyOn(structuredDataAuditApi, 'exports').mockResolvedValue([]);
  vi.spyOn(structuredDataAuditApi, 'export').mockRejectedValue(new Error('corrupt artifact'));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/structured-data-audits/audit-1/exports']}>
      <Routes>
        <Route
          path="/structured-data-audits/:auditId/exports"
          element={<StructuredDataAuditExportsPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
  await user.click(await screen.findByRole('button', { name: 'json' }));
  expect(await screen.findByText(/export could not be created/i)).toBeVisible();
});
