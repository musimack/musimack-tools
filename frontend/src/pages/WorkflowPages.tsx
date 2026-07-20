import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type SyntheticEvent,
} from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Spinner,
  StatusBadge,
  TableFoundation,
} from '../design-system/components';
import { downloadArtifact, workflowApi } from '../workflow/api';
import {
  crawlProfiles,
  scopeProfiles,
  type Artifact,
  type CrawlProfile,
  type CrawlRequest,
  type HistoricalJob,
  type HistoricalRun,
  type JobList,
  type JobResult,
  type JobStatus,
  type RecommendationDetail,
  type RecommendationPage,
  type ScopeProfile,
} from '../workflow/contracts';
import { useJobPolling } from '../workflow/useJobPolling';
import { useWorkflow } from '../workflow/WorkflowContext';

const profileCopy: Record<CrawlProfile, string> = {
  quick_audit: 'A small, fast sample for early signals.',
  standard_crawl: 'Balanced coverage for routine reviews.',
  deep_crawl: 'Broader limits for comprehensive analysis.',
  sitemap_only: 'Focus on sitemap recommendation output.',
};

const RECOMMENDATION_DEFAULT_PAGE_SIZE = 50;
const RECOMMENDATION_ALL_PAGE_SIZE = 50_000;
const RECOMMENDATION_PAGE_SIZES = new Set([50, 100, 500, RECOMMENDATION_ALL_PAGE_SIZE]);
const MAXIMUM_ACCEPTED_BYTES_OVERRIDE = 5_000_000_000;

const defaultRequest: CrawlRequest = {
  seed_url: '',
  scope_profile: 'exact_host',
  approved_hosts: [],
  crawl_profile: 'standard_crawl',
  overrides: {
    max_urls: null,
    max_depth: null,
    max_duration: null,
    max_accepted_bytes: null,
    max_concurrency: null,
    max_queue: null,
    min_delay: null,
    max_redirect_hops: null,
    max_response_bytes: null,
  },
  recommendation_profile: 'standard',
  recommendation_requested: true,
  xml_generation_requested: true,
  publication_requested: false,
  publication_dry_run: true,
  publication_root: null,
  existing_file_policy: 'fail',
  create_publication_directory: false,
  summary_writing_requested: false,
  summary_root: null,
  create_summary_directory: false,
  summary_dry_run: true,
  caller_label: 'frontend-workflow',
};

function stateTone(state: string | null): 'positive' | 'neutral' | 'warning' {
  if (state === 'completed') return 'positive';
  if (state === 'failed' || state === 'cancelled' || state === 'completed_with_warnings')
    return 'warning';
  return 'neutral';
}
function readable(value: string | null | undefined): string {
  return value ? value.replaceAll('_', ' ') : 'Not available';
}
function dateTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : 'Not available';
}
function safeExternalUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null;
  }
}
function useLoad<T>(loader: () => Promise<T>, dependencies: readonly unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  // Keep the caller's loader current while refresh remains stable for controls and effects.
  // eslint-disable-next-line react-hooks/refs
  loaderRef.current = loader;
  const dependencyKey = JSON.stringify(dependencies);
  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    void loaderRef
      .current()
      .then(setData)
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : 'The request failed.');
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);
  useEffect(() => {
    // The async loader immediately establishes this resource's loading state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [dependencyKey, refresh]);
  return { data, error, loading, refresh };
}

function Breadcrumbs({ children }: { children: ReactNode }) {
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      {children}
    </nav>
  );
}

export function JobsPage() {
  const { can } = useAuth();
  const { recentJobIds } = useWorkflow();
  const { data, error, loading, refresh } = useLoad<{
    live: JobList;
    history: { items: HistoricalJob[] };
  }>(async () => {
    const [live, history] = await Promise.all([
      workflowApi.jobs(),
      workflowApi.historyJobs({ page_size: 25 }),
    ]);
    return { live, history };
  }, []);
  const jobs = useMemo(() => {
    const byId = new Map((data?.live.items ?? []).map((item) => [item.job_id, item]));
    return [
      ...recentJobIds.map((jobId) => byId.get(jobId)).filter(Boolean),
      ...(data?.live.items ?? []).filter((item) => !recentJobIds.includes(item.job_id ?? '')),
    ] as JobStatus[];
  }, [data, recentJobIds]);
  return (
    <>
      <PageHeader eyebrow="Execution" title="Jobs">
        Submit a bounded crawl, then monitor its progress and sitemap output.
      </PageHeader>
      <div className="toolbar">
        {can('jobs.submit') ? (
          <Link className="button" to="/jobs/new">
            New crawl
          </Link>
        ) : null}
        <Button className="button--quiet" onClick={refresh}>
          Refresh
        </Button>
      </div>
      {error ? <ErrorState title="Jobs are unavailable">{error}</ErrorState> : null}
      {loading ? (
        <Spinner label="Loading jobs" />
      ) : jobs.length === 0 && (data?.history.items.length ?? 0) === 0 ? (
        <EmptyState title="No jobs yet">Create a crawl to begin.</EmptyState>
      ) : (
        <>
          <h2>Live and recently retained jobs</h2>
          {jobs.length ? (
            <JobTable jobs={jobs} />
          ) : (
            <Alert tone="neutral">No jobs are currently retained in live memory.</Alert>
          )}
          {data?.history.items.length ? (
            <>
              <h2>Durable history</h2>
              <HistoryJobTable jobs={data.history.items} />
            </>
          ) : null}
        </>
      )}
    </>
  );
}

function JobTable({ jobs }: { jobs: readonly JobStatus[] }) {
  return (
    <TableFoundation>
      <thead>
        <tr>
          <th>Job</th>
          <th>Status</th>
          <th>Stage</th>
          <th>Fetched</th>
          <th>Warnings</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.job_id}>
            <td>
              <code>{job.job_id}</code>
            </td>
            <td>
              <StatusBadge tone={stateTone(job.state)}>{readable(job.state)}</StatusBadge>
            </td>
            <td>{readable(job.active_stage)}</td>
            <td>{job.urls_fetched}</td>
            <td>{job.warning_count}</td>
            <td>{job.job_id ? <Link to={`/jobs/${job.job_id}`}>View</Link> : null}</td>
          </tr>
        ))}
      </tbody>
    </TableFoundation>
  );
}

export function NewCrawlPage() {
  const navigate = useNavigate();
  const { rememberJob } = useWorkflow();
  const [request, setRequest] = useState(defaultRequest);
  const [step, setStep] = useState<'edit' | 'review'>('edit');
  const [report, setReport] = useState<{
    valid: boolean;
    issues: { message: string; field: string | null }[];
    normalized_seed_url: string | null;
    selected_profile: string;
    effective_limits: Record<string, number> | null;
    scope_summary: string | null;
    run_id: string | null;
  } | null>(null);
  const [preflight, setPreflight] = useState<{
    state: string;
    findings: { message: string; severity: string }[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clientErrors, setClientErrors] = useState<string[]>([]);
  const dirty = request.seed_url.length > 0;
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => {
      window.removeEventListener('beforeunload', warn);
    };
  }, [dirty]);
  const validate = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const errors: string[] = [];
    try {
      const seed = new URL(request.seed_url);
      if (!['http:', 'https:'].includes(seed.protocol))
        errors.push('Seed URL must use HTTP or HTTPS.');
    } catch {
      errors.push('Enter a valid absolute seed URL.');
    }
    const normalizedHosts = request.approved_hosts.map((host) => host.toLowerCase());
    if (new Set(normalizedHosts).size !== normalizedHosts.length)
      errors.push('Approved hosts must not contain duplicates.');
    if (request.approved_hosts.some((host) => host.includes('/') || host.includes(':')))
      errors.push('Approved hosts must be host names only, without schemes, paths, or ports.');
    if (request.scope_profile === 'approved_hosts' && request.approved_hosts.length === 0)
      errors.push('Add at least one approved host for this scope policy.');
    const acceptedBytes = request.overrides.max_accepted_bytes;
    if (
      acceptedBytes !== null &&
      (!Number.isInteger(acceptedBytes) ||
        acceptedBytes < 1 ||
        acceptedBytes > MAXIMUM_ACCEPTED_BYTES_OVERRIDE)
    )
      errors.push(
        'Maximum accepted bytes must be a positive integer no greater than 5,000,000,000.',
      );
    setClientErrors(errors);
    if (errors.length) return;
    setBusy(true);
    setError(null);
    try {
      const [validation, readiness] = await Promise.all([
        workflowApi.validate(request),
        workflowApi.preflight(request),
      ]);
      setReport(validation);
      setPreflight(readiness);
      if (validation.valid) setStep('review');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Validation failed.');
    } finally {
      setBusy(false);
    }
  };
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await workflowApi.submit(request);
      const jobId = response.status.job_id;
      if (!jobId) throw new Error('The service accepted no job identifier.');
      rememberJob(jobId);
      void navigate(`/jobs/${jobId}/progress`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Submission failed.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Breadcrumbs>
        <Link to="/jobs">Jobs</Link>
        <span aria-hidden="true"> / </span>
        <span>New crawl</span>
      </Breadcrumbs>
      <PageHeader
        eyebrow="Guided workflow"
        title={step === 'edit' ? 'Configure a crawl' : 'Review and submit'}
      >
        {step === 'edit'
          ? 'Choose a profile, scope, and optional bounded overrides.'
          : 'Confirm the effective request and preflight findings.'}
      </PageHeader>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {step === 'edit' ? (
        <form className="workflow-form" onSubmit={(event) => void validate(event)}>
          {clientErrors.length ? (
            <Alert tone="error">
              <strong>Review the client checks.</strong>
              {clientErrors.map((item) => (
                <span key={item}>
                  <br />
                  {item}
                </span>
              ))}
            </Alert>
          ) : (
            <Alert tone="neutral">
              Backend validation is required before this request can run.
            </Alert>
          )}
          <Card>
            <h2>1. Seed and profile</h2>
            <label htmlFor="seed">Seed URL</label>
            <input
              id="seed"
              type="url"
              required
              value={request.seed_url}
              onChange={(event) => {
                setRequest({ ...request, seed_url: event.target.value });
              }}
              placeholder="https://example.com/"
            />
            <fieldset>
              <legend>Crawl profile</legend>
              <div className="option-grid">
                {crawlProfiles.map((profile) => (
                  <label key={profile}>
                    <input
                      type="radio"
                      name="profile"
                      checked={request.crawl_profile === profile}
                      onChange={() => {
                        setRequest({ ...request, crawl_profile: profile });
                      }}
                    />
                    <strong>{readable(profile)}</strong>
                    <small>{profileCopy[profile]}</small>
                  </label>
                ))}
              </div>
            </fieldset>
          </Card>
          <Card>
            <h2>2. Scope</h2>
            <label htmlFor="scope">Scope policy</label>
            <select
              id="scope"
              value={request.scope_profile}
              onChange={(event) => {
                setRequest({ ...request, scope_profile: event.target.value as ScopeProfile });
              }}
            >
              {scopeProfiles.map((scope) => (
                <option key={scope} value={scope}>
                  {readable(scope)}
                </option>
              ))}
            </select>
            {request.scope_profile === 'approved_hosts' ? (
              <>
                <label htmlFor="hosts">Approved hosts</label>
                <textarea
                  id="hosts"
                  value={request.approved_hosts.join('\n')}
                  onChange={(event) => {
                    setRequest({
                      ...request,
                      approved_hosts: event.target.value.split(/\s+/u).filter(Boolean),
                    });
                  }}
                  placeholder="www.example.com"
                />
              </>
            ) : null}
          </Card>
          <Card>
            <h2>3. Sitemap output</h2>
            <label>
              <input
                type="checkbox"
                checked={request.recommendation_requested}
                onChange={(event) => {
                  setRequest({ ...request, recommendation_requested: event.target.checked });
                }}
              />{' '}
              Generate sitemap recommendations
            </label>
            <label>
              <input
                type="checkbox"
                checked={request.xml_generation_requested}
                onChange={(event) => {
                  setRequest({ ...request, xml_generation_requested: event.target.checked });
                }}
              />{' '}
              Generate XML output
            </label>
            <fieldset disabled>
              <legend>Server-managed output options</legend>
              <label>
                <input type="checkbox" /> Publish generated sitemap files
              </label>
              <label>
                <input type="checkbox" checked readOnly /> Publication dry run
              </label>
              <label>
                <input type="checkbox" /> Write summary JSON
              </label>
              <label>
                <input type="checkbox" /> Write summary Markdown
              </label>
            </fieldset>
            <label htmlFor="recommendation-profile">Recommendation policy</label>
            <select
              id="recommendation-profile"
              value={request.recommendation_profile}
              onChange={(event) => {
                setRequest({
                  ...request,
                  recommendation_profile: event.target.value as 'standard' | 'strict',
                });
              }}
            >
              <option value="standard">Standard</option>
              <option value="strict">Strict</option>
            </select>
            <Alert tone="neutral">
              Server filesystem publication is intentionally unavailable in the browser UI; retained
              artifacts remain downloadable after completion.
            </Alert>
          </Card>
          <details className="card">
            <summary>Advanced bounded overrides</summary>
            <div className="override-grid">
              {(
                [
                  'max_urls',
                  'max_depth',
                  'max_duration',
                  'max_accepted_bytes',
                  'max_concurrency',
                  'max_queue',
                  'min_delay',
                  'max_redirect_hops',
                  'max_response_bytes',
                ] as const
              ).map((key) => (
                <label key={key}>
                  {key === 'max_accepted_bytes' ? 'Maximum accepted bytes' : readable(key)}
                  <input
                    type="number"
                    min={key === 'max_accepted_bytes' ? 1 : key === 'min_delay' ? 0.1 : 0}
                    max={key === 'max_accepted_bytes' ? MAXIMUM_ACCEPTED_BYTES_OVERRIDE : undefined}
                    step={
                      key === 'max_accepted_bytes' ? 1 : key === 'min_delay' ? 'any' : undefined
                    }
                    value={request.overrides[key] ?? ''}
                    onChange={(event) => {
                      setRequest({
                        ...request,
                        overrides: {
                          ...request.overrides,
                          [key]: event.target.value === '' ? null : Number(event.target.value),
                        },
                      });
                    }}
                  />
                </label>
              ))}
            </div>
          </details>
          {report && !report.valid ? (
            <Alert tone="error">
              {report.issues.map((detail) => (
                <span key={`${String(detail.field)}-${detail.message}`}>
                  {detail.field ? `${detail.field}: ` : ''}
                  {detail.message}
                  <br />
                </span>
              ))}
            </Alert>
          ) : null}
          <div className="toolbar">
            <Button type="submit" disabled={busy}>
              {busy ? 'Checking…' : 'Validate and preflight'}
            </Button>
            <Link
              className="button button--quiet"
              to="/jobs"
              onClick={(event) => {
                if (dirty && !window.confirm('Discard this crawl draft?')) event.preventDefault();
              }}
            >
              Cancel
            </Link>
            <Button
              type="button"
              className="button--quiet"
              onClick={() => {
                if (
                  !dirty ||
                  window.confirm('Reset this crawl to the standard profile defaults?')
                ) {
                  setRequest(defaultRequest);
                  setClientErrors([]);
                  setReport(null);
                  setPreflight(null);
                }
              }}
            >
              Reset
            </Button>
          </div>
        </form>
      ) : (
        <div className="content-grid">
          <Card>
            <h2>Request summary</h2>
            <dl className="detail-list">
              <div>
                <dt>Seed</dt>
                <dd>{request.seed_url}</dd>
              </div>
              <div>
                <dt>Profile</dt>
                <dd>{readable(request.crawl_profile)}</dd>
              </div>
              <div>
                <dt>Scope</dt>
                <dd>{readable(request.scope_profile)}</dd>
              </div>
              <div>
                <dt>Recommendations</dt>
                <dd>{request.recommendation_requested ? 'Enabled' : 'Disabled'}</dd>
              </div>
              <div>
                <dt>XML generation</dt>
                <dd>{request.xml_generation_requested ? 'Enabled' : 'Disabled'}</dd>
              </div>
            </dl>
            {report ? (
              <>
                <h3>Backend effective configuration</h3>
                <dl className="detail-list">
                  <div>
                    <dt>Normalized seed</dt>
                    <dd>{report.normalized_seed_url ?? 'Not returned'}</dd>
                  </div>
                  <div>
                    <dt>Selected profile</dt>
                    <dd>{readable(report.selected_profile)}</dd>
                  </div>
                  <div>
                    <dt>Scope</dt>
                    <dd>{report.scope_summary ?? 'Not returned'}</dd>
                  </div>
                  <div>
                    <dt>Run ID</dt>
                    <dd>{report.run_id ?? 'Not returned'}</dd>
                  </div>
                </dl>
                {report.effective_limits ? (
                  <ul className="check-list">
                    {Object.entries(report.effective_limits).map(([name, value]) => (
                      <li key={name}>
                        {readable(name)}: {value.toLocaleString()}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : null}
          </Card>
          <Card>
            <h2>Preflight</h2>
            <StatusBadge tone={preflight?.state === 'ready' ? 'positive' : 'warning'}>
              {readable(preflight?.state)}
            </StatusBadge>
            {preflight?.findings.map((finding) => (
              <p key={finding.message}>{finding.message}</p>
            ))}
            <div className="toolbar">
              <Button disabled={busy || preflight?.state !== 'ready'} onClick={() => void submit()}>
                {busy ? 'Submitting…' : 'Submit crawl'}
              </Button>
              <Button
                className="button--quiet"
                onClick={() => {
                  setStep('edit');
                }}
              >
                Back
              </Button>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}

export function JobDetailPage() {
  const { can } = useAuth();
  const { jobId } = useParams();
  const { status, progress, error, refresh } = useJobPolling(jobId);
  const [cancelling, setCancelling] = useState(false);
  if (!jobId) return <ErrorState title="Invalid job">No job identifier was provided.</ErrorState>;
  return (
    <>
      <Breadcrumbs>
        <Link to="/jobs">Jobs</Link>
        <span> / {jobId}</span>
      </Breadcrumbs>
      <PageHeader eyebrow="Live job" title="Job monitor">
        Status and progress refresh automatically while this job is active.
      </PageHeader>
      {error ? (
        <Alert tone="warning">
          {error}{' '}
          <Button className="button--quiet" onClick={refresh}>
            Retry now
          </Button>
        </Alert>
      ) : null}
      {!status ? (
        <Spinner label="Loading job" />
      ) : (
        <>
          <div className="metric-grid">
            <Card>
              <span>Status</span>
              <strong>{readable(status.state)}</strong>
              <small>
                {status.queue_position
                  ? `Queue position ${String(status.queue_position)}`
                  : readable(status.run_lifecycle)}
              </small>
            </Card>
            <Card>
              <span>URLs fetched</span>
              <strong>{status.urls_fetched}</strong>
              <small>{status.urls_discovered} discovered</small>
            </Card>
            <Card>
              <span>Current stage</span>
              <strong>{readable(status.active_stage)}</strong>
              <small>
                {status.warning_count} warnings · {status.failure_count} failures
              </small>
            </Card>
          </div>
          <Card className="workflow-panel">
            <div className="card-heading">
              <div>
                <h2>Progress events</h2>
                <p>
                  {progress?.history_truncated
                    ? 'Showing the most recent bounded events.'
                    : 'Recent server-reported events.'}
                </p>
              </div>
              <StatusBadge tone={stateTone(status.state)}>{readable(status.state)}</StatusBadge>
            </div>
            <ol className="timeline">
              {progress?.history.map((event) => (
                <li key={event.sequence}>
                  <strong>{readable(event.code)}</strong>
                  <span>{event.explanation}</span>
                </li>
              ))}
            </ol>
            <div className="toolbar">
              {status.result_available ? (
                <Link className="button" to={`/jobs/${jobId}/results`}>
                  View results
                </Link>
              ) : null}
              <Button className="button--quiet" onClick={refresh}>
                Refresh now
              </Button>
              {!status.terminal && can('jobs.cancel') ? (
                <Button
                  disabled={cancelling}
                  className="button--danger"
                  onClick={() => {
                    if (!window.confirm('Request cancellation for this job?')) return;
                    setCancelling(true);
                    void workflowApi
                      .cancel(jobId)
                      .then(refresh)
                      .finally(() => {
                        setCancelling(false);
                      });
                  }}
                >
                  {cancelling ? 'Cancelling…' : 'Cancel job'}
                </Button>
              ) : null}
            </div>
          </Card>
        </>
      )}
    </>
  );
}

export function JobResultPage() {
  const { can } = useAuth();
  const { jobId } = useParams();
  const { data, error, loading, refresh } = useLoad<JobResult>(
    () => workflowApi.result(jobId ?? ''),
    [jobId],
  );
  if (!jobId) return <ErrorState title="Invalid job">No job identifier was provided.</ErrorState>;
  return (
    <>
      <Breadcrumbs>
        <Link to={`/jobs/${jobId}`}>Job</Link>
        <span> / Results</span>
      </Breadcrumbs>
      <PageHeader eyebrow="Completed output" title="Crawl results">
        Review aggregate crawl, recommendation, XML, publication, warning, and failure results.
      </PageHeader>
      {error ? (
        <ErrorState title="Results are unavailable">
          {error}
          <br />
          <Button onClick={refresh}>Retry</Button>
        </ErrorState>
      ) : loading || !data ? (
        <Spinner label="Loading results" />
      ) : (
        <>
          <div className="metric-grid">
            <Card>
              <span>Lifecycle</span>
              <strong>{readable(data.run_lifecycle)}</strong>
              <small>{readable(data.job_state)}</small>
            </Card>
            <Card>
              <span>XML documents</span>
              <strong>{data.xml_document_count ?? 0}</strong>
              <small>{data.xml_entry_count ?? 0} entries</small>
            </Card>
            <Card>
              <span>Recommendations</span>
              <strong>
                {data.recommendation_counts.reduce((sum, item) => sum + item.count, 0)}
              </strong>
              <small>{data.warning_codes.length} warning codes</small>
            </Card>
          </div>
          <div className="content-grid">
            <Card>
              <h2>Stage outcomes</h2>
              <ul className="check-list">
                {data.stage_states.map((item) => (
                  <li key={item.name}>
                    {readable(item.name)}: {readable(item.value)}
                  </li>
                ))}
              </ul>
            </Card>
            <Card>
              <h2>Next actions</h2>
              <p>Inspect per-URL sitemap decisions or retrieve retained output artifacts.</p>
              <div className="toolbar">
                <Link className="button" to={`/jobs/${jobId}/results/recommendations`}>
                  Review recommendations
                </Link>
                <Link className="button button--quiet" to="/artifacts">
                  Artifacts
                </Link>
                {can('jobs.submit') && data.run_id ? (
                  <Link
                    className="button button--quiet"
                    to={`/audits/metadata/new?run=${encodeURIComponent(data.run_id)}`}
                  >
                    Run Metadata Audit
                  </Link>
                ) : null}
              </div>
            </Card>
          </div>
          {data.failure_codes.length ? (
            <Alert tone="error">Failures: {data.failure_codes.join(', ')}</Alert>
          ) : null}
          {data.warning_codes.length ? (
            <Alert tone="warning">Warnings: {data.warning_codes.join(', ')}</Alert>
          ) : null}
        </>
      )}
    </>
  );
}

export function RecommendationPage() {
  const { jobId } = useParams();
  const [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get('offset') ?? 0) || 0);
  const requestedLimit = Number(params.get('limit') ?? RECOMMENDATION_DEFAULT_PAGE_SIZE);
  const limit = RECOMMENDATION_PAGE_SIZES.has(requestedLimit)
    ? requestedLimit
    : RECOMMENDATION_DEFAULT_PAGE_SIZE;
  const state = params.get('state');
  const reason = params.get('reason');
  const text = params.get('text');
  const filters = {
    offset,
    limit,
    ...(state ? { state } : {}),
    ...(reason ? { reason } : {}),
    ...(text ? { text } : {}),
  };
  const { data, error, loading } = useLoad<RecommendationPage>(
    () => workflowApi.recommendations(jobId ?? '', filters),
    [jobId, offset, limit, filters.state, filters.reason, filters.text],
  );
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'offset') next.delete('offset');
    setParams(next);
  };
  const resetFilters = () => {
    const next = new URLSearchParams();
    if (params.has('limit')) next.set('limit', String(limit));
    setParams(next);
  };
  if (!jobId) return <ErrorState title="Invalid job">No job identifier was provided.</ErrorState>;
  return (
    <>
      <Breadcrumbs>
        <Link to={`/jobs/${jobId}/results`}>Results</Link>
        <span> / Recommendations</span>
      </Breadcrumbs>
      <PageHeader eyebrow="Sitemap review" title="URL recommendations">
        Filter bounded, server-retained decisions without exposing crawl response bodies.
      </PageHeader>
      <div className="filter-bar">
        <label>
          Rows per page
          <select
            value={String(limit)}
            onChange={(event) => {
              update('limit', event.target.value);
            }}
          >
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="500">500</option>
            <option value="50000">All</option>
          </select>
        </label>
        <label>
          State
          <select
            value={filters.state ?? ''}
            onChange={(event) => {
              update('state', event.target.value);
            }}
          >
            <option value="">All</option>
            <option value="include">Include</option>
            <option value="exclude">Exclude</option>
            <option value="review">Review</option>
            <option value="indeterminate">Indeterminate</option>
          </select>
        </label>
        <label>
          Reason
          <input
            value={filters.reason ?? ''}
            onChange={(event) => {
              update('reason', event.target.value);
            }}
          />
        </label>
        <label>
          URL contains
          <input
            value={filters.text ?? ''}
            onChange={(event) => {
              update('text', event.target.value);
            }}
          />
        </label>
        <Button onClick={resetFilters}>Reset filters</Button>
      </div>
      {error ? (
        <ErrorState title="Recommendations are unavailable">{error}</ErrorState>
      ) : loading || !data ? (
        <Spinner label="Loading recommendations" />
      ) : data.items.length === 0 ? (
        <EmptyState title="No matching recommendations">
          Adjust the filters or return to the result summary.
        </EmptyState>
      ) : (
        <>
          <TableFoundation>
            <thead>
              <tr>
                <th>URL</th>
                <th>Decision</th>
                <th>Reason</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.url}>
                  <td>
                    <Link
                      to={`/jobs/${jobId}/results/recommendations/${String(item.sequence)}${params.toString() ? `?${params.toString()}` : ''}`}
                    >
                      {item.url}
                    </Link>
                    <small>{item.explanation}</small>
                    {safeExternalUrl(item.url) ? (
                      <small>
                        <a
                          href={safeExternalUrl(item.url) ?? undefined}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Open crawled URL in new tab
                        </a>
                      </small>
                    ) : null}
                  </td>
                  <td>
                    <StatusBadge tone={item.state === 'include' ? 'positive' : 'warning'}>
                      {readable(item.state)}
                    </StatusBadge>
                  </td>
                  <td>{readable(item.primary_reason)}</td>
                  <td>{item.http_status ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </TableFoundation>
          <div className="toolbar">
            <Button
              disabled={offset === 0}
              onClick={() => {
                update('offset', String(Math.max(0, offset - limit)));
              }}
            >
              Previous
            </Button>
            <span>
              {offset + 1}–{offset + data.returned_count} of {data.total}
            </span>
            <Button
              disabled={!data.has_more}
              onClick={() => {
                update('offset', String(offset + limit));
              }}
            >
              Next
            </Button>
          </div>
          {limit === RECOMMENDATION_ALL_PAGE_SIZE && data.total > limit ? (
            <Alert tone="warning">
              All is bounded to 50,000 retained recommendations per request.
            </Alert>
          ) : null}
        </>
      )}
    </>
  );
}

function DetailValue({ value }: { value: string | number | boolean | null | undefined }) {
  if (value === null || value === undefined || value === '') return <>Not retained</>;
  if (typeof value === 'boolean') return <>{value ? 'Yes' : 'No'}</>;
  return <>{value}</>;
}

function DetailList({ values }: { values: readonly string[] }) {
  return values.length ? (
    <ul>
      {values.map((value) => (
        <li key={value}>{readable(value)}</li>
      ))}
    </ul>
  ) : (
    <>None retained</>
  );
}

export function RecommendationDetailPage() {
  const { jobId, sequence } = useParams();
  const [params] = useSearchParams();
  const [copyState, setCopyState] = useState<string | null>(null);
  const parsedSequence = Number(sequence);
  const validSequence = Number.isInteger(parsedSequence) && parsedSequence >= 1;
  const { data, error, loading } = useLoad<RecommendationDetail>(
    () => workflowApi.recommendation(jobId ?? '', parsedSequence),
    [jobId, parsedSequence],
  );
  if (!jobId || !validSequence)
    return (
      <ErrorState title="Invalid recommendation">The detail identifier is invalid.</ErrorState>
    );
  const returnSearch = params.toString();
  const returnTarget = `/jobs/${jobId}/results/recommendations${returnSearch ? `?${returnSearch}` : ''}`;
  if (error) return <ErrorState title="Recommendation details are unavailable">{error}</ErrorState>;
  if (loading || !data) return <Spinner label="Loading recommendation details" />;
  const item = data.recommendation;
  const externalUrl = safeExternalUrl(item.url);
  const copyUrl = () => {
    void navigator.clipboard.writeText(item.url).then(
      () => {
        setCopyState('URL copied.');
      },
      () => {
        setCopyState('The URL could not be copied.');
      },
    );
  };
  return (
    <>
      <Breadcrumbs>
        <Link to={returnTarget}>Recommendations</Link>
        <span> / Detail</span>
      </Breadcrumbs>
      <PageHeader eyebrow="Sitemap review" title="URL recommendation detail">
        Review retained, bounded evidence without exposing crawl response bodies or raw HTML.
      </PageHeader>
      <Card>
        <h2>Actions</h2>
        <div className="toolbar">
          <Link className="button" to={returnTarget}>
            Return to recommendations
          </Link>
          {externalUrl ? (
            <a className="button" href={externalUrl} target="_blank" rel="noopener noreferrer">
              Open crawled URL in new tab
            </a>
          ) : (
            <span>External navigation is unavailable for this URL scheme.</span>
          )}
          <Button onClick={copyUrl}>Copy URL</Button>
        </div>
        <p>
          Destination: <code>{item.url}</code>
        </p>
        {copyState ? <p role="status">{copyState}</p> : null}
      </Card>
      <div className="detail-grid">
        <Card>
          <h2>Recommendation</h2>
          <dl>
            <dt>Decision</dt>
            <dd>{readable(item.state)}</dd>
            <dt>Primary reason</dt>
            <dd>{readable(item.primary_reason)}</dd>
            <dt>Explanation</dt>
            <dd>{item.explanation}</dd>
            <dt>Determinacy</dt>
            <dd>{readable(item.determinacy)}</dd>
            <dt>All reason codes</dt>
            <dd>
              <DetailList values={data.reason_codes} />
            </dd>
          </dl>
          <h3>Warnings</h3>
          {data.warning_details.length ? (
            <ul>
              {data.warning_details.map((warning) => (
                <li key={`${warning.source}:${warning.code}`}>
                  <strong>{readable(warning.code)}</strong>: {warning.explanation}{' '}
                  <small>({readable(warning.source)})</small>
                </li>
              ))}
            </ul>
          ) : (
            <p>No retained warning details.</p>
          )}
        </Card>
        <Card>
          <h2>URL and fetch evidence</h2>
          <dl>
            <dt>Requested URL</dt>
            <dd>{item.requested_url}</dd>
            <dt>Evaluated URL</dt>
            <dd>{item.url}</dd>
            <dt>Final URL</dt>
            <dd>
              <DetailValue value={item.final_url} />
            </dd>
            <dt>HTTP status</dt>
            <dd>
              <DetailValue value={item.http_status} />
            </dd>
            <dt>Content type</dt>
            <dd>
              <DetailValue value={item.content_type} />
            </dd>
            <dt>Fetch outcome</dt>
            <dd>
              <DetailValue value={data.fetch_outcome} />
            </dd>
            <dt>Fetch failure</dt>
            <dd>
              <DetailValue value={item.fetch_failure_code ?? data.page_failure_code} />
            </dd>
            <dt>Redirect source</dt>
            <dd>
              <DetailValue value={item.redirect_source} />
            </dd>
            <dt>Redirect destination</dt>
            <dd>
              <DetailValue value={item.redirect_final_url} />
            </dd>
            <dt>Redirect loop</dt>
            <dd>
              <DetailValue value={data.redirect_loop} />
            </dd>
            <dt>Redirect evidence truncated</dt>
            <dd>
              <DetailValue value={data.redirect_truncated} />
            </dd>
            <dt>Robots permission</dt>
            <dd>
              {item.robots_available ? <DetailValue value={item.robots_allowed} /> : 'Unavailable'}
            </dd>
            <dt>Robots reason</dt>
            <dd>
              <DetailValue value={item.robots_reason_code} />
            </dd>
          </dl>
          <h3>Redirect chain</h3>
          {data.redirect_chain.length ? (
            <ol>
              {data.redirect_chain.map((redirect) => (
                <li key={redirect.sequence}>
                  {redirect.status_code}: {redirect.source_url} →{' '}
                  <DetailValue value={redirect.target_url} />
                  {redirect.failure_code ? ` (${readable(redirect.failure_code)})` : ''}
                </li>
              ))}
            </ol>
          ) : (
            <p>No redirect hops retained.</p>
          )}
          <h3>Indexability</h3>
          <dl>
            <dt>Generic directives</dt>
            <dd>
              <DetailList values={item.generic_directives} />
            </dd>
            <dt>Crawler-specific directives</dt>
            <dd>
              <DetailList values={item.crawler_specific_directives} />
            </dd>
            <dt>Conflicting evidence</dt>
            <dd>
              <DetailValue value={item.indexability_conflict} />
            </dd>
          </dl>
        </Card>
        <Card>
          <h2>Metadata</h2>
          <dl>
            <dt>Title</dt>
            <dd>
              <DetailValue value={data.title} />
            </dd>
            <dt>Title state</dt>
            <dd>
              <DetailValue value={data.title_presence} />
            </dd>
            <dt>Meta description</dt>
            <dd>
              <DetailValue value={data.meta_description} />
            </dd>
            <dt>Description state</dt>
            <dd>
              <DetailValue value={data.description_presence} />
            </dd>
            <dt>Canonical</dt>
            <dd>
              <DetailValue value={item.canonical_url} />
            </dd>
            <dt>Canonical state</dt>
            <dd>
              <DetailValue value={data.canonical_presence} />
            </dd>
            <dt>Canonical conflict</dt>
            <dd>
              <DetailValue value={item.canonical_conflicting} />
            </dd>
            <dt>Meta robots</dt>
            <dd>
              {data.meta_robots.length
                ? data.meta_robots
                    .map((group) => `${group.agent}: ${group.directives.join(', ')}`)
                    .join('; ')
                : 'None retained'}
            </dd>
            <dt>X-Robots-Tag</dt>
            <dd>
              {data.x_robots_tag.length
                ? data.x_robots_tag
                    .map((group) => `${group.agent}: ${group.directives.join(', ')}`)
                    .join('; ')
                : 'None retained'}
            </dd>
            <dt>Metadata warning codes</dt>
            <dd>
              <DetailList values={data.metadata_warning_codes} />
            </dd>
          </dl>
        </Card>
        <Card>
          <h2>Context</h2>
          <dl>
            <dt>Crawl depth</dt>
            <dd>
              <DetailValue value={data.crawl_depth} />
            </dd>
            <dt>Sitemap membership</dt>
            <dd>
              <DetailValue value={data.sitemap_membership} />
            </dd>
            <dt>Page evidence identifier</dt>
            <dd className="wrap-anywhere">
              <DetailValue value={data.evidence_id} />
            </dd>
            <dt>Evidence state</dt>
            <dd>
              <DetailValue value={data.evidence_state} />
            </dd>
          </dl>
          <h3>Decision evidence</h3>
          <ol>
            {data.rule_evidence.map((rule) => (
              <li key={rule.rule_id}>
                <strong>{readable(rule.outcome)}</strong>: {rule.explanation}
                {rule.reason_code ? ` (${readable(rule.reason_code)})` : ''}
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </>
  );
}

export function ArtifactsPage() {
  const { can } = useAuth();
  const { data, error, loading } = useLoad(() => workflowApi.artifacts(), []);
  return (
    <>
      <PageHeader eyebrow="Retained output" title="Artifacts">
        Inspect safe metadata and explicitly download available output files.
      </PageHeader>
      {error ? (
        <ErrorState title="Artifacts are unavailable">{error}</ErrorState>
      ) : loading || !data ? (
        <Spinner label="Loading artifacts" />
      ) : data.items.length === 0 ? (
        <EmptyState title="No retained artifacts">
          Completed sitemap jobs may produce downloadable output here.
        </EmptyState>
      ) : (
        <ArtifactTable artifacts={data.items} canDownload={can('artifacts.download')} />
      )}
    </>
  );
}
function ArtifactTable({
  artifacts,
  canDownload,
}: {
  artifacts: Artifact[];
  canDownload: boolean;
}) {
  return (
    <TableFoundation>
      <thead>
        <tr>
          <th>Filename</th>
          <th>Type</th>
          <th>Integrity</th>
          <th>Size</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {artifacts.map((artifact) => (
          <tr key={artifact.artifact_id}>
            <td>
              <Link to={`/artifacts/${artifact.artifact_id}`}>{artifact.filename}</Link>
            </td>
            <td>{readable(artifact.artifact_type)}</td>
            <td>{readable(artifact.integrity_state)}</td>
            <td>{artifact.byte_count.toLocaleString()} bytes</td>
            <td>
              <Button
                disabled={!artifact.download_available || !canDownload}
                onClick={() => void downloadArtifact(artifact.artifact_id, artifact.filename)}
              >
                Download
              </Button>
            </td>
          </tr>
        ))}
      </tbody>
    </TableFoundation>
  );
}

export function ArtifactDetailPage() {
  const { can } = useAuth();
  const { artifactId } = useParams();
  const { data, error, loading } = useLoad(
    () => workflowApi.artifact(artifactId ?? ''),
    [artifactId],
  );
  if (!artifactId)
    return <ErrorState title="Invalid artifact">No artifact identifier was provided.</ErrorState>;
  return (
    <>
      <Breadcrumbs>
        <Link to="/artifacts">Artifacts</Link>
        <span> / Detail</span>
      </Breadcrumbs>
      <PageHeader eyebrow="Artifact metadata" title={data?.filename ?? 'Artifact'}>
        Verify lifecycle, integrity, and retention before explicit download.
      </PageHeader>
      {error ? (
        <ErrorState title="Artifact unavailable">{error}</ErrorState>
      ) : loading || !data ? (
        <Spinner label="Loading artifact" />
      ) : (
        <Card>
          <dl className="detail-list">
            <div>
              <dt>Type</dt>
              <dd>{readable(data.artifact_type)}</dd>
            </div>
            <div>
              <dt>Lifecycle</dt>
              <dd>{readable(data.lifecycle_state)}</dd>
            </div>
            <div>
              <dt>Integrity</dt>
              <dd>{readable(data.integrity_state)}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{dateTime(data.created_at)}</dd>
            </div>
            <div>
              <dt>Content type</dt>
              <dd>{data.content_type}</dd>
            </div>
            <div>
              <dt>Size</dt>
              <dd>{data.byte_count.toLocaleString()} bytes</dd>
            </div>
          </dl>
          <Button
            disabled={!data.download_available || !can('artifacts.download')}
            onClick={() => void downloadArtifact(data.artifact_id, data.filename)}
          >
            Download artifact
          </Button>
        </Card>
      )}
    </>
  );
}

export function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const state = params.get('state') ?? '';
  const seed = params.get('seed') ?? '';
  const { data, error, loading } = useLoad(
    () => workflowApi.historyJobs({ page_size: 50, state, seed }),
    [state, seed],
  );
  return (
    <>
      <PageHeader eyebrow="Durable records" title="History">
        Review retained job and run records independently of in-memory live state.
      </PageHeader>
      <form
        className="filter-bar"
        onSubmit={(event) => {
          event.preventDefault();
        }}
      >
        <label>
          State
          <input
            value={state}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              if (event.target.value) next.set('state', event.target.value);
              else next.delete('state');
              setParams(next);
            }}
          />
        </label>
        <label>
          Seed contains
          <input
            value={seed}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              if (event.target.value) next.set('seed', event.target.value);
              else next.delete('seed');
              setParams(next);
            }}
          />
        </label>
      </form>
      {error ? (
        <ErrorState title="History unavailable">{error}</ErrorState>
      ) : loading || !data ? (
        <Spinner label="Loading history" />
      ) : data.items.length === 0 ? (
        <EmptyState title="No matching history">Adjust filters or complete a job.</EmptyState>
      ) : (
        <HistoryJobTable jobs={data.items} />
      )}
    </>
  );
}
function HistoryJobTable({ jobs }: { jobs: HistoricalJob[] }) {
  return (
    <TableFoundation>
      <thead>
        <tr>
          <th>Seed</th>
          <th>State</th>
          <th>Attempts</th>
          <th>Submitted</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.job_id}>
            <td>{job.seed}</td>
            <td>
              <StatusBadge tone={stateTone(job.state)}>{readable(job.state)}</StatusBadge>
            </td>
            <td>{job.attempt_count}</td>
            <td>{dateTime(job.submitted_at)}</td>
            <td>
              <Link to={`/history/jobs/${job.job_id}`}>Detail</Link>
            </td>
          </tr>
        ))}
      </tbody>
    </TableFoundation>
  );
}

export function HistoryJobPage() {
  const { jobId } = useParams();
  const { data, error, loading } = useLoad(() => workflowApi.historyJob(jobId ?? ''), [jobId]);
  if (!jobId) return <ErrorState title="Invalid job">No job identifier was provided.</ErrorState>;
  return (
    <>
      <Breadcrumbs>
        <Link to="/history">History</Link>
        <span> / Job</span>
      </Breadcrumbs>
      <PageHeader eyebrow="Durable job" title={data?.seed ?? 'Historical job'}>
        This retained record remains available after live job eviction.
      </PageHeader>
      {error ? (
        <ErrorState title="History unavailable">{error}</ErrorState>
      ) : loading || !data ? (
        <Spinner label="Loading historical job" />
      ) : (
        <Card>
          <dl className="detail-list">
            <div>
              <dt>State</dt>
              <dd>{readable(data.state)}</dd>
            </div>
            <div>
              <dt>Attempts</dt>
              <dd>{data.attempt_count}</dd>
            </div>
            <div>
              <dt>Submitted</dt>
              <dd>{dateTime(data.submitted_at)}</dd>
            </div>
            <div>
              <dt>Terminal</dt>
              <dd>{dateTime(data.terminal_at)}</dd>
            </div>
          </dl>
          <Link className="button" to={`/history/runs/${data.run_id}`}>
            View run
          </Link>
        </Card>
      )}
    </>
  );
}

export function HistoryRunPage() {
  const { runId } = useParams();
  const { data, error, loading } = useLoad<HistoricalRun>(
    () => workflowApi.historyRun(runId ?? ''),
    [runId],
  );
  const related = useLoad(async () => {
    const kinds = await Promise.all(
      ['stages', 'warnings', 'failures', 'artifacts'].map((kind) =>
        workflowApi.related(runId ?? '', kind as 'stages' | 'warnings' | 'failures' | 'artifacts'),
      ),
    );
    return kinds;
  }, [runId]);
  if (!runId) return <ErrorState title="Invalid run">No run identifier was provided.</ErrorState>;
  return (
    <>
      <Breadcrumbs>
        <Link to="/history">History</Link>
        <span> / Run</span>
      </Breadcrumbs>
      <PageHeader eyebrow="Durable run" title={data?.seed ?? 'Historical run'}>
        Inspect lifecycle, counts, stages, warnings, failures, and artifact references.
      </PageHeader>
      {error ? (
        <ErrorState title="Run unavailable">{error}</ErrorState>
      ) : loading || !data ? (
        <Spinner label="Loading historical run" />
      ) : (
        <>
          <div className="metric-grid">
            <Card>
              <span>Lifecycle</span>
              <strong>{readable(data.lifecycle)}</strong>
              <small>{readable(data.current_stage)}</small>
            </Card>
            <Card>
              <span>Crawled</span>
              <strong>{data.crawl_count}</strong>
              <small>{data.recommendation_count} recommendations</small>
            </Card>
            <Card>
              <span>Artifacts</span>
              <strong>{data.artifact_count}</strong>
              <small>
                {data.warning_count} warnings · {data.failure_count} failures
              </small>
            </Card>
          </div>
          {related.loading ? (
            <Spinner label="Loading related history" />
          ) : related.error ? (
            <Alert tone="warning">{related.error}</Alert>
          ) : (
            <div className="content-grid">
              {['Stages', 'Warnings', 'Failures', 'Artifacts'].map((label, index) => (
                <Card key={label}>
                  <h2>{label}</h2>
                  <p>{related.data?.[index]?.items.length ?? 0} retained records</p>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
