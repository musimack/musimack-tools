import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach } from 'vitest';
import { workflowApi } from '../workflow/api';
import type { PreflightResult, ValidationReport } from '../workflow/contracts';
import { WorkflowProvider } from '../workflow/WorkflowContext';
import { NewCrawlPage } from './WorkflowPages';

const validReport: ValidationReport = {
  valid: true,
  issues: [],
  normalized_seed_url: 'https://example.test/',
  selected_profile: 'standard_crawl',
  requested_stages: ['crawl', 'recommendation', 'xml_generation'],
  effective_limits: { maximum_urls: 1000, maximum_depth: 5 },
  scope_summary: 'exact_host',
  publication_requested: false,
  summary_requested: false,
  run_id: 'run-safe',
  downstream_versions: [],
};
const readyPreflight: PreflightResult = {
  state: 'ready',
  validation: validReport,
  findings: [{ severity: 'info', code: 'advisory_only', message: 'Preflight is advisory.' }],
};

function renderForm() {
  return render(
    <MemoryRouter>
      <WorkflowProvider>
        <NewCrawlPage />
      </WorkflowProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('new crawl workflow', () => {
  test('starts with the accepted standard profile and browser-safe output choices', () => {
    renderForm();
    expect(screen.getByRole('radio', { name: /standard crawl/i })).toBeChecked();
    expect(
      screen.getByRole('checkbox', { name: 'Generate sitemap recommendations' }),
    ).toBeChecked();
    expect(
      screen.getByRole('checkbox', { name: 'Publish generated sitemap files' }),
    ).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Write summary JSON' })).toBeDisabled();
  });

  test('keeps explicit profile changes controlled', async () => {
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByRole('radio', { name: /sitemap only/i }));
    expect(screen.getByRole('radio', { name: /sitemap only/i })).toBeChecked();
    expect(screen.getByRole('radio', { name: /standard crawl/i })).not.toBeChecked();
  });

  test('blocks a non-http seed before contacting backend validation', async () => {
    const validate = vi.spyOn(workflowApi, 'validate');
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText('Seed URL'), 'ftp://example.test/');
    await user.click(screen.getByRole('button', { name: 'Validate and preflight' }));
    expect(await screen.findByText('Seed URL must use HTTP or HTTPS.')).toBeInTheDocument();
    expect(validate).not.toHaveBeenCalled();
  });

  test('rejects duplicate approved hosts as a client usability check', async () => {
    const validate = vi.spyOn(workflowApi, 'validate');
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText('Seed URL'), 'https://example.test/');
    await user.selectOptions(screen.getByLabelText('Scope policy'), 'approved_hosts');
    fireEvent.change(screen.getByLabelText('Approved hosts'), {
      target: { value: 'www.example.test\nWWW.EXAMPLE.TEST' },
    });
    await user.click(screen.getByRole('button', { name: 'Validate and preflight' }));
    expect(
      await screen.findByText('Approved hosts must not contain duplicates.'),
    ).toBeInTheDocument();
    expect(validate).not.toHaveBeenCalled();
  });

  test('shows backend effective values and a separate ready preflight confirmation', async () => {
    vi.spyOn(workflowApi, 'validate').mockResolvedValue(validReport);
    vi.spyOn(workflowApi, 'preflight').mockResolvedValue(readyPreflight);
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText('Seed URL'), 'https://example.test/');
    await user.click(screen.getByRole('button', { name: 'Validate and preflight' }));
    expect(await screen.findByRole('heading', { name: 'Review and submit' })).toBeInTheDocument();
    expect(screen.getAllByText('https://example.test/')).toHaveLength(2);
    expect(screen.getByText('1,000', { exact: false })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Submit crawl' })).toBeEnabled();
  });

  test('reset requires confirmation once the draft is dirty', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText('Seed URL'), 'https://example.test/');
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(window.confirm).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('Seed URL')).toHaveValue('');
  });
});
