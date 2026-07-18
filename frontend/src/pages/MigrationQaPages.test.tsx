import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach } from 'vitest';
import { migrationQaApi, type MigrationQaPage } from '../migration-qa/api';
import {
  MigrationQaExportsPage,
  MigrationQaInventoryPage,
  NewMigrationQaPage,
} from './MigrationQaPages';

const auth = vi.hoisted(() => ({ allowed: true }));
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ can: () => auth.allowed }) }));
vi.mock('../workflow/api', () => ({ downloadArtifact: vi.fn().mockResolvedValue(undefined) }));

const page = (next_cursor: string | null = null): MigrationQaPage => ({
  items: [
    {
      stable_id: 'finding-1',
      code: 'destination_404',
      category: 'destination',
      severity: 'error',
      confidence: 'high',
      source_url: 'https://old.example/long/path',
      destination_url: 'https://www.example/long/path',
    },
  ],
  next_cursor,
  page_size: 25,
  total: 2,
});

afterEach(() => {
  auth.allowed = true;
  vi.restoreAllMocks();
});

test('creation previews input, exposes policy controls, checks readiness, executes, and polls', async () => {
  vi.spyOn(migrationQaApi, 'create').mockResolvedValue({ project_id: 'project-1' });
  vi.spyOn(migrationQaApi, 'ingestSources').mockResolvedValue({ accepted_rows: 1 });
  vi.spyOn(migrationQaApi, 'ingestRedirects').mockResolvedValue({ accepted_rows: 1 });
  vi.spyOn(migrationQaApi, 'readiness').mockResolvedValue({ readiness: 'ready', reasons: [] });
  vi.spyOn(migrationQaApi, 'execute').mockResolvedValue({ state: 'running' });
  const detail = vi
    .spyOn(migrationQaApi, 'detail')
    .mockResolvedValue({ state: 'completed_with_warnings' });
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/migration-qa/new']}>
      <Routes>
        <Route path="/migration-qa/new" element={<NewMigrationQaPage />} />
        <Route path="/migration-qa/:projectId" element={<h1>Completed dashboard</h1>} />
      </Routes>
    </MemoryRouter>,
  );
  await user.type(screen.getByLabelText('Project name'), 'Launch QA');
  await user.type(screen.getByLabelText('Destination crawl run ID'), 'run-destination');
  await user.type(screen.getByLabelText('Destination origin'), 'https://www.example');
  await user.click(screen.getByLabelText('Compare internal links'));
  expect(screen.getAllByText(/Parsing preview:/)).toHaveLength(2);
  await user.click(screen.getByRole('button', { name: 'Create, ingest, and check readiness' }));
  expect(await screen.findByText('ready')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Execute migration QA' }));
  expect(await screen.findByRole('heading', { name: 'Completed dashboard' })).toBeVisible();
  expect(detail).toHaveBeenCalledWith('project-1');
  const createInput = vi.mocked(migrationQaApi.create).mock.calls[0]?.[0];
  expect(createInput?.name).toBe('Launch QA');
  const policy = createInput?.policy;
  expect(typeof policy).toBe('object');
  expect((policy as Record<string, unknown>).compare_internal_links).toBe(true);
});

test('preview surfaces bounded row validation errors', async () => {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <NewMigrationQaPage />
    </MemoryRouter>,
  );
  const input = screen.getByLabelText('Source inventory CSV, TSV, or URL list');
  await user.clear(input);
  await user.type(input, 'source_url,destination_url\n,https://www.example/a');
  expect(screen.getByText('Row 2 has no source URL.')).toBeVisible();
  expect(
    screen.getByRole('button', { name: 'Create, ingest, and check readiness' }),
  ).toBeDisabled();
});

test('resource filters reset cursors and paginate through bounded evidence', async () => {
  const resource = vi.spyOn(migrationQaApi, 'resource').mockResolvedValue(page('cursor-2'));
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/migration-qa/project-1/findings']}>
      <Routes>
        <Route path="/migration-qa/:projectId/:resource" element={<MigrationQaInventoryPage />} />
      </Routes>
    </MemoryRouter>,
  );
  const table = await screen.findByRole('table');
  expect(within(table).getByText('destination 404')).toBeVisible();
  await user.type(screen.getByLabelText('Source search'), 'old.example');
  await waitFor(() => {
    expect(resource).toHaveBeenLastCalledWith(
      'project-1',
      'findings',
      expect.objectContaining({ source_search: 'old.example', cursor: null }),
    );
  });
  await user.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => {
    expect(resource).toHaveBeenLastCalledWith(
      'project-1',
      'findings',
      expect.objectContaining({ cursor: 'cursor-2' }),
    );
  });
  await user.click(screen.getByRole('button', { name: 'Reset filters' }));
  expect(screen.getByLabelText('Source search')).toHaveValue('');
});

test('artifact history exposes eight actions and authenticated download controls', async () => {
  vi.spyOn(migrationQaApi, 'exports').mockResolvedValue([
    {
      id: 'export-1',
      artifact_id: 'artifact-1',
      filename: 'findings.csv',
      export_format: 'findings_csv',
      row_count: 2,
      state: 'completed',
    },
  ]);
  render(
    <MemoryRouter initialEntries={['/migration-qa/project-1/exports']}>
      <Routes>
        <Route path="/migration-qa/:projectId/exports" element={<MigrationQaExportsPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'findings.csv' })).toHaveAttribute(
    'href',
    '/artifacts/artifact-1',
  );
  expect(screen.getAllByRole('button', { name: /csv|json|markdown/u })).toHaveLength(8);
  expect(screen.getByRole('button', { name: 'Download' })).toBeEnabled();
});

test('viewer receives read-only export history and no mutation or download authority', async () => {
  auth.allowed = false;
  vi.spyOn(migrationQaApi, 'exports').mockResolvedValue([
    {
      id: 'export-1',
      artifact_id: 'artifact-1',
      filename: 'report.json',
      export_format: 'json',
      row_count: 1,
      state: 'completed',
    },
  ]);
  render(
    <MemoryRouter>
      <MigrationQaExportsPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'report.json' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Download' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'json' })).toBeDisabled();
});
