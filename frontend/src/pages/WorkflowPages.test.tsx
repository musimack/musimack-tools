import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach } from 'vitest';
import { workflowApi } from '../workflow/api';
import type {
  PreflightResult,
  Recommendation,
  RecommendationDetail,
  RecommendationPage as RecommendationPageData,
  ValidationReport,
} from '../workflow/contracts';
import { WorkflowProvider } from '../workflow/WorkflowContext';
import { NewCrawlPage, RecommendationDetailPage, RecommendationPage } from './WorkflowPages';

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

function recommendation(index: number): Recommendation {
  const url = `https://example.test/page-${String(index).padStart(2, '0')}`;
  return {
    sequence: index,
    url,
    requested_url: url,
    final_url: url,
    state: 'include',
    determinacy: 'determinate',
    primary_reason: 'eligible_html_page',
    explanation: 'Available evidence supports XML sitemap inclusion',
    http_status: 200,
    content_type: 'text/html',
    fetch_failure_code: null,
    canonical_url: url,
    canonical_conflicting: false,
    redirect_source: false,
    redirect_hops: 0,
    redirect_final_url: null,
    robots_available: true,
    robots_allowed: true,
    robots_reason_code: null,
    generic_directives: [],
    crawler_specific_directives: [],
    indexability_conflict: false,
    configured_exclusions: [],
  };
}

function recommendationDetail(url = 'http://127.0.0.1:8765/noindex'): RecommendationDetail {
  return {
    recommendation: {
      ...recommendation(5),
      sequence: 5,
      url,
      requested_url: url,
      final_url: url,
      state: 'exclude',
      primary_reason: 'generic_noindex',
      explanation: 'Trustworthy generic indexability evidence contains noindex',
      generic_directives: ['noindex', 'follow'],
    },
    reason_codes: ['generic_noindex'],
    rule_evidence: [
      {
        rule_id: '08_hard_exclusion',
        outcome: 'exclude',
        reason_code: 'generic_noindex',
        explanation: 'Trustworthy generic indexability evidence contains noindex',
      },
    ],
    warning_details: [
      { code: 'short_title', explanation: 'The title is short.', source: 'metadata' },
    ],
    metadata_warning_codes: ['short_title'],
    evidence_id: 'evidence-safe-1',
    crawl_depth: 1,
    fetch_outcome: 'success',
    evidence_state: 'complete',
    page_failure_code: null,
    title_presence: 'present',
    title: 'Noindex Page',
    description_presence: 'present',
    meta_description: 'This page is intentionally noindex.',
    canonical_presence: 'present',
    meta_robots: [{ agent: '*', directives: ['noindex', 'follow'] }],
    x_robots_tag: [],
    redirect_chain: [],
    redirect_truncated: false,
    redirect_loop: false,
    sitemap_membership: false,
    application_service_version: 'application-service-v1',
  };
}

function recommendationPage(offset: number, total = 120, limit = 50): RecommendationPageData {
  const returned = Math.min(limit, Math.max(0, total - offset));
  return {
    job_id: 'job-safe_1',
    run_id: 'run-safe_1',
    offset,
    limit,
    total,
    returned_count: returned,
    has_more: offset + returned < total,
    items: Array.from({ length: returned }, (_, index) => recommendation(offset + index + 1)),
  };
}

function renderRecommendations(entry = '/jobs/job-safe_1/results/recommendations') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route
          path="/jobs/:jobId/results/recommendations"
          element={
            <>
              <RecommendationPage />
              <LocationSearch />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

function renderRecommendationDetail(
  entry = '/jobs/job-safe_1/results/recommendations/5?limit=100&offset=100&state=exclude&reason=noindex',
) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route
          path="/jobs/:jobId/results/recommendations/:sequence"
          element={<RecommendationDetailPage />}
        />
        <Route
          path="/jobs/:jobId/results/recommendations"
          element={
            <>
              <span>Recommendation list</span>
              <LocationSearch />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

function LocationSearch() {
  return <span data-testid="location-search">{useLocation().search}</span>;
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

  test('renders a bounded optional maximum accepted bytes control', () => {
    renderForm();
    const input = screen.getByRole('spinbutton', { name: 'Maximum accepted bytes' });
    expect(input).toHaveValue(null);
    expect(input).toHaveAttribute('min', '1');
    expect(input).toHaveAttribute('max', '5000000000');
    expect(input).toHaveAttribute('step', '1');
    expect(screen.getAllByRole('spinbutton', { name: 'Maximum accepted bytes' })).toHaveLength(1);
  });

  test('accepts a decimal minimum request delay through validation, preflight, and submission', async () => {
    const report = {
      ...validReport,
      effective_limits: {
        maximum_urls: 25,
        minimum_request_delay_seconds: 0.1,
      },
    };
    const validate = vi.spyOn(workflowApi, 'validate').mockResolvedValue(report);
    const preflight = vi
      .spyOn(workflowApi, 'preflight')
      .mockResolvedValue({ ...readyPreflight, validation: report });
    const submit = vi.spyOn(workflowApi, 'submit').mockResolvedValue({
      outcome: 'accepted',
      status: {
        outcome: 'found',
        job_id: 'job-safe',
        run_id: 'run-safe',
        attempt_number: 1,
        state: 'accepted',
        queue_position: 1,
        active_stage: null,
        run_lifecycle: 'accepted',
        urls_discovered: 0,
        urls_fetched: 0,
        recommendation_counts: null,
        xml_document_count: null,
        xml_entry_count: null,
        publication_file_count: null,
        warning_count: 0,
        failure_count: 0,
        cancellation_requested: false,
        terminal: false,
        result_available: false,
      },
    });
    const user = userEvent.setup();
    renderForm();
    const delay = screen.getByRole('spinbutton', { name: 'min delay' });
    expect(delay).toHaveAttribute('min', '0.1');
    expect(delay).toHaveAttribute('step', 'any');
    await user.type(screen.getByLabelText('Seed URL'), 'https://example.test/');
    await user.type(delay, '0.1');
    await user.click(screen.getByRole('button', { name: 'Validate and preflight' }));

    expect(await screen.findByRole('heading', { name: 'Review and submit' })).toBeInTheDocument();
    expect(validate.mock.calls[0]?.[0].overrides.min_delay).toBe(0.1);
    expect(preflight.mock.calls[0]?.[0].overrides.min_delay).toBe(0.1);
    expect(screen.getByText('minimum request delay seconds: 0.1')).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Submit crawl' }));
    expect(submit.mock.calls[0]?.[0].overrides.min_delay).toBe(0.1);
  });

  test('preserves an explicit accepted-byte limit through review and submission', async () => {
    const report = {
      ...validReport,
      effective_limits: {
        maximum_urls: 25,
        maximum_accepted_bytes: 40_000_000,
      },
    };
    const validate = vi.spyOn(workflowApi, 'validate').mockResolvedValue(report);
    const preflight = vi
      .spyOn(workflowApi, 'preflight')
      .mockResolvedValue({ ...readyPreflight, validation: report });
    const submit = vi.spyOn(workflowApi, 'submit').mockResolvedValue({
      outcome: 'accepted',
      status: {
        outcome: 'found',
        job_id: 'job-safe',
        run_id: 'run-safe',
        attempt_number: 1,
        state: 'accepted',
        queue_position: 1,
        active_stage: null,
        run_lifecycle: 'accepted',
        urls_discovered: 0,
        urls_fetched: 0,
        recommendation_counts: null,
        xml_document_count: null,
        xml_entry_count: null,
        publication_file_count: null,
        warning_count: 0,
        failure_count: 0,
        cancellation_requested: false,
        terminal: false,
        result_available: false,
      },
    });
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText('Seed URL'), 'https://example.test/');
    await user.type(screen.getByRole('spinbutton', { name: 'Maximum accepted bytes' }), '40000000');
    await user.click(screen.getByRole('button', { name: 'Validate and preflight' }));

    expect(await screen.findByRole('heading', { name: 'Review and submit' })).toBeInTheDocument();
    expect(validate).toHaveBeenCalledOnce();
    expect(validate.mock.calls[0]?.[0].overrides.max_accepted_bytes).toBe(40_000_000);
    expect(preflight).toHaveBeenCalledOnce();
    expect(preflight.mock.calls[0]?.[0].overrides.max_accepted_bytes).toBe(40_000_000);
    expect(screen.getByText('maximum accepted bytes: 40,000,000')).toBeVisible();
    expect(screen.queryByText('maximum accepted bytes: 500,000,000')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Submit crawl' }));
    expect(submit).toHaveBeenCalledOnce();
    expect(submit.mock.calls[0]?.[0].overrides.max_accepted_bytes).toBe(40_000_000);
  });

  test.each(['0', '-1', '1.5', '5000000001'])(
    'blocks invalid maximum accepted bytes %s before API validation',
    async (value) => {
      const validate = vi.spyOn(workflowApi, 'validate');
      const preflight = vi.spyOn(workflowApi, 'preflight');
      const user = userEvent.setup();
      renderForm();
      await user.type(screen.getByLabelText('Seed URL'), 'https://example.test/');
      fireEvent.change(screen.getByRole('spinbutton', { name: 'Maximum accepted bytes' }), {
        target: { value },
      });
      await user.click(screen.getByRole('button', { name: 'Validate and preflight' }));
      expect(screen.getByRole('heading', { name: 'Configure a crawl' })).toBeVisible();
      expect(validate).not.toHaveBeenCalled();
      expect(preflight).not.toHaveBeenCalled();
    },
  );

  test('rejects nonnumeric accepted-byte input without creating a conflicting value', () => {
    renderForm();
    const input = screen.getByRole('spinbutton', { name: 'Maximum accepted bytes' });
    fireEvent.change(input, { target: { value: 'not-a-number' } });
    expect(input).toHaveValue(null);
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

describe('retained recommendation pagination', () => {
  test('moves through exact stable row ranges and returns to the first page', async () => {
    const load = vi
      .spyOn(workflowApi, 'recommendations')
      .mockImplementation((_jobId, values) =>
        Promise.resolve(recommendationPage(values.offset ?? 0, 75, values.limit ?? 50)),
      );
    const user = userEvent.setup();
    renderRecommendations();

    const table = await screen.findByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(51);
    expect(screen.getByText('https://example.test/page-01')).toBeVisible();
    expect(screen.getByText('https://example.test/page-50')).toBeVisible();
    expect(screen.getByText('1–50 of 75')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('https://example.test/page-51')).toBeVisible();
    expect(screen.getByText('https://example.test/page-75')).toBeVisible();
    expect(screen.queryByText('https://example.test/page-50')).not.toBeInTheDocument();
    expect(screen.getByText('51–75 of 75')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled();
    expect(load).toHaveBeenLastCalledWith(
      'job-safe_1',
      expect.objectContaining({ offset: 50, limit: 50 }),
    );

    await user.click(screen.getByRole('button', { name: 'Previous' }));
    expect(await screen.findByText('https://example.test/page-01')).toBeVisible();
    expect(screen.getByText('1–50 of 75')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
  });

  test('retains the requested page in the route query for refresh and direct navigation', async () => {
    const load = vi
      .spyOn(workflowApi, 'recommendations')
      .mockImplementation((_jobId, values) =>
        Promise.resolve(recommendationPage(values.offset ?? 0, 120, values.limit ?? 50)),
      );
    renderRecommendations('/jobs/job-safe_1/results/recommendations?limit=50&offset=50');

    expect(await screen.findByText('https://example.test/page-51')).toBeVisible();
    expect(screen.getByText('51–100 of 120')).toBeVisible();
    expect(load).toHaveBeenCalledWith(
      'job-safe_1',
      expect.objectContaining({ offset: 50, limit: 50 }),
    );
  });

  test('paginates filtered totals without duplicates or unbounded loading', async () => {
    const load = vi
      .spyOn(workflowApi, 'recommendations')
      .mockImplementation((_jobId, values) =>
        Promise.resolve(
          recommendationPage(
            values.offset ?? 0,
            values.state === 'include' ? 65 : 120,
            values.limit ?? 50,
          ),
        ),
      );
    const user = userEvent.setup();
    renderRecommendations();

    await screen.findByText('1–50 of 120');
    await user.selectOptions(screen.getByLabelText('State'), 'include');
    await waitFor(() => {
      expect(load).toHaveBeenLastCalledWith(
        'job-safe_1',
        expect.objectContaining({ offset: 0, limit: 50, state: 'include' }),
      );
    });
    expect(await screen.findByText('1–50 of 65')).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('https://example.test/page-51')).toBeVisible();
    expect(screen.getByText('https://example.test/page-65')).toBeVisible();
    expect(screen.queryByText('https://example.test/page-50')).not.toBeInTheDocument();
    expect(screen.getByText('51–65 of 65')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(load).toHaveBeenLastCalledWith(
      'job-safe_1',
      expect.objectContaining({ offset: 50, limit: 50, state: 'include' }),
    );
  });

  test.each([
    ['State', 'select', 'include', { state: 'include' }],
    ['Reason', 'input', 'eligible', { reason: 'eligible' }],
    ['URL contains', 'input', '/guide', { text: '/guide' }],
  ] as const)(
    '%s filtering resets an existing page to offset zero',
    async (label, kind, value, filter) => {
      const load = vi
        .spyOn(workflowApi, 'recommendations')
        .mockImplementation((_jobId, values) =>
          Promise.resolve(recommendationPage(values.offset ?? 0, 120, values.limit ?? 50)),
        );
      const user = userEvent.setup();
      renderRecommendations('/jobs/job-safe_1/results/recommendations?limit=50&offset=50');
      await screen.findByText('51–100 of 120');

      if (kind === 'select') await user.selectOptions(screen.getByLabelText(label), value);
      else fireEvent.change(screen.getByLabelText(label), { target: { value } });

      await waitFor(() => {
        expect(load).toHaveBeenLastCalledWith(
          'job-safe_1',
          expect.objectContaining({ offset: 0, limit: 50, ...filter }),
        );
      });
      expect(await screen.findByText('1–50 of 120')).toBeVisible();
      expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    },
  );

  test.each([
    ['50', 50],
    ['100', 100],
    ['500', 500],
    ['All', 50_000],
  ] as const)('uses the bounded %s page-size option', async (option, expectedLimit) => {
    const load = vi
      .spyOn(workflowApi, 'recommendations')
      .mockImplementation((_jobId, values) =>
        Promise.resolve(recommendationPage(values.offset ?? 0, 50, values.limit ?? 50)),
      );
    renderRecommendations(
      `/jobs/job-safe_1/results/recommendations?limit=${String(expectedLimit)}`,
    );

    await waitFor(() => {
      expect(load).toHaveBeenLastCalledWith(
        'job-safe_1',
        expect.objectContaining({ offset: 0, limit: expectedLimit }),
      );
    });
    expect(await screen.findByText('1–50 of 50')).toBeVisible();
    expect(screen.getByLabelText('Rows per page')).toHaveValue(String(expectedLimit));
    expect(
      within(screen.getByLabelText('Rows per page')).getByRole('option', { name: option }),
    ).toBeInTheDocument();
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(51);
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByTestId('location-search')).toHaveTextContent(
      `?limit=${String(expectedLimit)}`,
    );
  });

  test('preserves the selected page size on refresh and resets offset when it changes', async () => {
    const load = vi
      .spyOn(workflowApi, 'recommendations')
      .mockImplementation((_jobId, values) =>
        Promise.resolve(recommendationPage(values.offset ?? 0, 250, values.limit ?? 50)),
      );
    const user = userEvent.setup();
    renderRecommendations('/jobs/job-safe_1/results/recommendations?limit=100&offset=100');

    expect(await screen.findByText('101–200 of 250')).toBeVisible();
    expect(screen.getByLabelText('Rows per page')).toHaveValue('100');
    expect(load).toHaveBeenCalledWith(
      'job-safe_1',
      expect.objectContaining({ offset: 100, limit: 100 }),
    );

    await user.selectOptions(screen.getByLabelText('Rows per page'), '500');
    expect(await screen.findByText('1–250 of 250')).toBeVisible();
    expect(load).toHaveBeenLastCalledWith(
      'job-safe_1',
      expect.objectContaining({ offset: 0, limit: 500 }),
    );
    expect(screen.getByTestId('location-search')).toHaveTextContent('?limit=500');
  });

  test('Reset filters clears filter parameters while preserving page size and ordering', async () => {
    const load = vi
      .spyOn(workflowApi, 'recommendations')
      .mockImplementation((_jobId, values) =>
        Promise.resolve(recommendationPage(values.offset ?? 0, 120, values.limit ?? 50)),
      );
    const user = userEvent.setup();
    renderRecommendations(
      '/jobs/job-safe_1/results/recommendations?limit=100&offset=100&state=review&reason=canonical&text=guide',
    );
    await screen.findByRole('table');

    await user.click(screen.getByRole('button', { name: 'Reset filters' }));
    await waitFor(() => {
      expect(load).toHaveBeenLastCalledWith('job-safe_1', { offset: 0, limit: 100 });
    });
    expect(screen.getByLabelText('Rows per page')).toHaveValue('100');
    expect(screen.getByLabelText('State')).toHaveValue('');
    expect(screen.getByLabelText('Reason')).toHaveValue('');
    expect(screen.getByLabelText('URL contains')).toHaveValue('');
    expect(screen.getByTestId('location-search')).toHaveTextContent('?limit=100');
    expect(await screen.findByText('1–100 of 120')).toBeVisible();
    expect(screen.getByText('https://example.test/page-01')).toBeVisible();
  });

  test('reason filtering paginates with page size 50 and remains bounded in All mode', async () => {
    const load = vi
      .spyOn(workflowApi, 'recommendations')
      .mockImplementation((_jobId, values) =>
        Promise.resolve(
          recommendationPage(values.offset ?? 0, values.reason ? 60 : 120, values.limit ?? 50),
        ),
      );
    const user = userEvent.setup();
    renderRecommendations();
    await screen.findByText('1–50 of 120');

    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'eligible' } });
    expect(await screen.findByText('1–50 of 60')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('51–60 of 60')).toBeVisible();
    expect(load).toHaveBeenLastCalledWith(
      'job-safe_1',
      expect.objectContaining({ offset: 50, limit: 50, reason: 'eligible' }),
    );

    await user.selectOptions(screen.getByLabelText('Rows per page'), 'All');
    expect(await screen.findByText('1–60 of 60')).toBeVisible();
    expect(load).toHaveBeenLastCalledWith(
      'job-safe_1',
      expect.objectContaining({ offset: 0, limit: 50_000, reason: 'eligible' }),
    );
  });
});

describe('URL recommendation detail', () => {
  test('uses internal primary navigation, preserves list state, and keeps a separate safe source action', async () => {
    vi.spyOn(workflowApi, 'recommendations').mockResolvedValue(recommendationPage(50, 120, 50));
    renderRecommendations(
      '/jobs/job-safe_1/results/recommendations?limit=50&offset=50&state=exclude&reason=noindex&text=fixture',
    );

    const row = (await screen.findByText('https://example.test/page-51')).closest('tr');
    expect(row).not.toBeNull();
    const internal = within(row!).getByRole('link', { name: 'https://example.test/page-51' });
    expect(internal).toHaveAttribute(
      'href',
      '/jobs/job-safe_1/results/recommendations/51?limit=50&offset=50&state=exclude&reason=noindex&text=fixture',
    );
    const external = within(row!).getByRole('link', {
      name: 'Open crawled URL in new tab',
    });
    expect(external).toHaveAttribute('href', 'https://example.test/page-51');
    expect(external).toHaveAttribute('target', '_blank');
    expect(external).toHaveAttribute('rel', 'noopener noreferrer');
  });

  test('supports a direct route refresh and exposes bounded diagnostic evidence without bodies', async () => {
    const load = vi.spyOn(workflowApi, 'recommendation').mockResolvedValue(recommendationDetail());
    renderRecommendationDetail();

    expect(await screen.findByRole('heading', { name: 'URL recommendation detail' })).toBeVisible();
    expect(load).toHaveBeenCalledWith('job-safe_1', 5);
    expect(screen.getAllByText('generic noindex').length).toBeGreaterThan(0);
    expect(screen.getByText('Noindex Page')).toBeVisible();
    expect(screen.getByText('This page is intentionally noindex.')).toBeVisible();
    expect(screen.getByText('evidence-safe-1')).toBeVisible();
    expect(screen.getByText('evidence-safe-1').closest('dd')).toHaveClass('wrap-anywhere');
    expect(document.body).not.toHaveTextContent('<private>secret-body</private>');

    const open = screen.getByRole('link', { name: 'Open crawled URL in new tab' });
    expect(open).toHaveAttribute('href', 'http://127.0.0.1:8765/noindex');
    expect(open).toHaveAttribute('target', '_blank');
    expect(open).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText(/Destination:/)).toHaveTextContent('http://127.0.0.1:8765/noindex');
  });

  test('returns to the exact filters, offset, and limit and exposes keyboard-accessible actions', async () => {
    vi.spyOn(workflowApi, 'recommendation').mockResolvedValue(recommendationDetail());
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText');
    renderRecommendationDetail();

    const copy = await screen.findByRole('button', { name: 'Copy URL' });
    copy.focus();
    expect(copy).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(writeText).toHaveBeenCalledWith('http://127.0.0.1:8765/noindex');
    expect(await screen.findByRole('status')).toHaveTextContent('URL copied.');

    const back = screen.getByRole('link', { name: 'Return to recommendations' });
    expect(back).toHaveAttribute(
      'href',
      '/jobs/job-safe_1/results/recommendations?limit=100&offset=100&state=exclude&reason=noindex',
    );
    await user.click(back);
    expect(await screen.findByText('Recommendation list')).toBeVisible();
    expect(screen.getByTestId('location-search')).toHaveTextContent(
      '?limit=100&offset=100&state=exclude&reason=noindex',
    );
  });

  test.each(['javascript:alert(1)', 'data:text/html,unsafe', 'file:///C:/secret'])(
    'rejects an unsafe external URL scheme: %s',
    async (url) => {
      vi.spyOn(workflowApi, 'recommendation').mockResolvedValue(recommendationDetail(url));
      renderRecommendationDetail();
      expect(
        await screen.findByText('External navigation is unavailable for this URL scheme.'),
      ).toBeVisible();
      expect(
        screen.queryByRole('link', { name: 'Open crawled URL in new tab' }),
      ).not.toBeInTheDocument();
      expect(screen.getByText(/Destination:/)).toHaveTextContent(url);
    },
  );

  test('shows a safe unavailable state for legacy jobs without retained details', async () => {
    vi.spyOn(workflowApi, 'recommendation').mockRejectedValue(
      new Error('Detailed recommendations are not retained for this job.'),
    );
    renderRecommendationDetail();
    expect(
      await screen.findByRole('heading', { name: 'Recommendation details are unavailable' }),
    ).toBeVisible();
    expect(
      screen.getByText('Detailed recommendations are not retained for this job.'),
    ).toBeVisible();
  });
});
