import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, vi } from 'vitest';
import { auditApi } from '../audits/api';
import type { MetadataAuditRunCandidate } from '../audits/contracts';
import { workflowApi } from '../workflow/api';
import type { JobResult } from '../workflow/contracts';
import { NewAuditPage } from './AuditPages';
import { JobResultPage } from './WorkflowPages';

const authState = vi.hoisted(() => ({ canSubmit: true }));
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    can: (permission: string) => permission === 'jobs.submit' && authState.canSubmit,
  }),
}));

const eligible: MetadataAuditRunCandidate = {
  run_id: 'run-current',
  job_id: 'job-current',
  seed_url: 'https://example.test/',
  completed_at: '2026-07-19T22:09:24Z',
  job_status: 'completed_with_warnings',
  crawl_profile: 'standard_crawl',
  page_evidence_count: 50,
  evidence_state: 'partial',
  eligible: true,
  ineligibility_reason: null,
};
const ineligible: MetadataAuditRunCandidate = {
  ...eligible,
  run_id: 'run-pending',
  job_id: 'job-pending',
  seed_url: 'https://pending.test/',
  completed_at: null,
  job_status: 'running',
  page_evidence_count: 0,
  evidence_state: 'unavailable',
  eligible: false,
  ineligibility_reason: 'The crawl has not reached a terminal state.',
};

afterEach(() => {
  authState.canSubmit = true;
  vi.restoreAllMocks();
});

function renderNewAudit(entry = '/audits/metadata/new') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/audits/metadata/new" element={<NewAuditPage />} />
        <Route path="/audits/metadata/:auditId" element={<h1>Audit dashboard</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

test('selects a completed crawl without requiring internal ID knowledge', async () => {
  vi.spyOn(auditApi, 'runCandidates').mockResolvedValue([eligible, ineligible]);
  renderNewAudit('/audits/metadata/new?run=run-current');

  expect(await screen.findByText('https://example.test/')).toBeVisible();
  expect(screen.getByText(/completed with warnings · standard crawl · 50 pages/i)).toBeVisible();
  expect(screen.getByText(/Evidence: partial/i)).toBeVisible();
  expect(screen.getByText(/2026/)).toBeVisible();
  expect(screen.getByText('Run ID: run-current')).toBeVisible();
  expect(screen.queryByLabelText('Run ID')).not.toBeInTheDocument();
  expect(screen.getByRole('radio', { name: /https:\/\/example.test\//i })).toBeChecked();
  expect(screen.getByRole('button', { name: 'Run Metadata Audit' })).toBeEnabled();
  expect(screen.getByRole('radio', { name: /https:\/\/pending.test\//i })).toBeDisabled();
  expect(screen.getByText('The crawl has not reached a terminal state.')).toBeVisible();
});

test('searches candidates and preserves direct run selection across route refresh', async () => {
  vi.spyOn(auditApi, 'runCandidates').mockResolvedValue([eligible, ineligible]);
  const user = userEvent.setup();
  const view = renderNewAudit('/audits/metadata/new?run=run-current');
  await screen.findByText('https://example.test/');
  await user.type(screen.getByLabelText('Search by site, status, profile, or date'), 'pending');
  expect(screen.queryByText('https://example.test/')).not.toBeInTheDocument();
  expect(screen.getByText('https://pending.test/')).toBeVisible();
  view.unmount();
  renderNewAudit('/audits/metadata/new?run=run-current');
  expect(await screen.findByRole('radio', { name: /https:\/\/example.test\//i })).toBeChecked();
});

test('defaults only when recent eligible runs belong to one site', async () => {
  vi.spyOn(auditApi, 'runCandidates').mockResolvedValue([
    eligible,
    { ...eligible, run_id: 'run-older', completed_at: '2026-07-18T22:09:24Z' },
  ]);
  renderNewAudit();
  const radios = await screen.findAllByRole('radio', { name: /https:\/\/example.test\//i });
  expect(radios).toHaveLength(2);
  await waitFor(() => {
    expect(radios[0]).toBeChecked();
  });
  expect(radios[1]).not.toBeChecked();
});

test('does not silently select an unrelated site and handles deleted runs safely', async () => {
  vi.spyOn(auditApi, 'runCandidates').mockResolvedValue([
    eligible,
    { ...eligible, run_id: 'run-other', seed_url: 'https://other.test/' },
  ]);
  const view = renderNewAudit();
  await screen.findByText('https://example.test/');
  expect(screen.getByRole('button', { name: 'Run Metadata Audit' })).toBeDisabled();
  view.unmount();
  renderNewAudit('/audits/metadata/new?run=run-deleted');
  expect(await screen.findByText(/selected run is unavailable, deleted/i)).toBeVisible();
});

test('explains when no eligible runs exist', async () => {
  vi.spyOn(auditApi, 'runCandidates').mockResolvedValue([]);
  renderNewAudit();
  expect(
    await screen.findByText('No completed runs with retained page evidence are available.'),
  ).toBeVisible();
  expect(screen.getByRole('button', { name: 'Run Metadata Audit' })).toBeDisabled();
});

test('runs the audit using the selected candidate', async () => {
  vi.spyOn(auditApi, 'runCandidates').mockResolvedValue([eligible]);
  const create = vi.spyOn(auditApi, 'create').mockResolvedValue({
    audit_id: 'audit-current',
    job_id: eligible.job_id,
    run_id: eligible.run_id,
    seed_url: eligible.seed_url,
    state: 'completed',
    created_at: eligible.completed_at ?? '',
    completed_at: eligible.completed_at,
    page_count: 50,
    issue_count: 1,
    partial: true,
    failure_code: null,
    export_available: false,
  });
  const user = userEvent.setup();
  renderNewAudit('/audits/metadata/new?run=run-current');
  await user.click(await screen.findByRole('button', { name: 'Run Metadata Audit' }));
  await waitFor(() => {
    expect(create).toHaveBeenCalledWith('run-current');
  });
  expect(await screen.findByRole('heading', { name: 'Audit dashboard' })).toBeVisible();
});

test('completed crawl results carry the run directly into metadata audit creation', async () => {
  const result: JobResult = {
    outcome: 'found',
    job_id: 'job-current',
    run_id: 'run-current',
    attempt_number: 1,
    job_state: 'completed_with_warnings',
    run_lifecycle: 'completed_with_warnings',
    stage_states: [],
    crawl_counts: [],
    crawl_error_codes: [],
    recommendation_counts: [],
    xml_document_count: 1,
    xml_entry_count: 30,
    publication_state: null,
    published_file_count: 0,
    publication_filenames: [],
    warning_codes: [],
    failure_codes: [],
  };
  vi.spyOn(workflowApi, 'result').mockResolvedValue(result);
  render(
    <MemoryRouter initialEntries={['/jobs/job-current/results']}>
      <Routes>
        <Route path="/jobs/:jobId/results" element={<JobResultPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('link', { name: 'Run Metadata Audit' })).toHaveAttribute(
    'href',
    '/audits/metadata/new?run=run-current',
  );
});

test('viewer crawl results remain read-only', async () => {
  authState.canSubmit = false;
  vi.spyOn(workflowApi, 'result').mockResolvedValue({
    outcome: 'found',
    job_id: 'job-current',
    run_id: 'run-current',
    attempt_number: 1,
    job_state: 'completed',
    run_lifecycle: 'completed',
    stage_states: [],
    crawl_counts: [],
    crawl_error_codes: [],
    recommendation_counts: [],
    xml_document_count: 0,
    xml_entry_count: 0,
    publication_state: null,
    published_file_count: 0,
    publication_filenames: [],
    warning_codes: [],
    failure_codes: [],
  });
  render(
    <MemoryRouter initialEntries={['/jobs/job-current/results']}>
      <Routes>
        <Route path="/jobs/:jobId/results" element={<JobResultPage />} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByRole('heading', { name: 'Crawl results' });
  expect(screen.queryByRole('link', { name: 'Run Metadata Audit' })).not.toBeInTheDocument();
});
