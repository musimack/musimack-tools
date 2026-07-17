import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
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
import { sitemapAuditApi } from '../sitemap-audits/api';
import {
  actions,
  type CreateValues,
  type ExportFormat,
  type Page,
  type SitemapAudit,
} from '../sitemap-audits/contracts';

function useLoad<T>(factory: () => Promise<T>, dependencies: readonly unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({
    data: null,
    error: null,
  });
  useEffect(() => {
    let active = true;
    void factory()
      .then((data) => {
        if (active) setState({ data, error: null });
      })
      .catch(() => {
        if (active) setState({ data: null, error: 'The sitemap audit data could not be loaded.' });
      });
    return () => {
      active = false;
    };
    // Endpoint factories intentionally follow route/query dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);
  return state;
}

function Loading({ error }: { error: string | null }) {
  return error ? (
    <ErrorState title="Sitemap audit unavailable">{error}</ErrorState>
  ) : (
    <Card aria-busy="true">
      <Spinner label="Loading sitemap audit" />
    </Card>
  );
}

function Crumbs({ auditId, current }: { auditId?: string; current: string }) {
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <Link to="/sitemap-audits">Sitemap Audits</Link>
      {auditId ? (
        <>
          <span aria-hidden="true">/</span>
          <Link to={`/sitemap-audits/${auditId}`}>Audit</Link>
        </>
      ) : null}
      <span aria-hidden="true">/</span>
      <span aria-current="page">{current}</span>
    </nav>
  );
}

export function SitemapAuditsPage() {
  const state = useLoad(() => sitemapAuditApi.list(), []);
  return (
    <>
      <PageHeader eyebrow="Existing sitemap quality" title="Sitemap Audits">
        Compare discovered sitemap inventory with durable crawl and recommendation evidence.
      </PageHeader>
      <p>
        <Link className="button" to="/sitemap-audits/new">
          New sitemap audit
        </Link>
      </p>
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No sitemap audits">
          Choose a completed crawl run with durable page evidence to begin.
        </EmptyState>
      ) : (
        <TableFoundation>
          <caption>Durable sitemap audits</caption>
          <thead>
            <tr>
              <th>Site</th>
              <th>Run</th>
              <th>Status</th>
              <th>Documents</th>
              <th>URLs</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((audit) => (
              <tr key={audit.audit_id}>
                <td className="wrap-anywhere">
                  <Link to={`/sitemap-audits/${audit.audit_id}`}>{audit.seed_url}</Link>
                </td>
                <td>{audit.run_id}</td>
                <td>
                  <StatusBadge tone={audit.state.startsWith('completed') ? 'positive' : 'neutral'}>
                    {audit.state.replaceAll('_', ' ')}
                  </StatusBadge>
                </td>
                <td>{audit.document_count}</td>
                <td>{audit.unique_url_count}</td>
                <td>{audit.review_count}</td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}

export function NewSitemapAuditPage() {
  const navigate = useNavigate();
  const [values, setValues] = useState<CreateValues>({
    runId: '',
    explicitSitemapUrl: '',
    discoverRobots: true,
    discoverCommonLocations: true,
  });
  const [candidates, setCandidates] = useState<string[]>([]);
  const [status, setStatus] = useState<'idle' | 'discovering' | 'running' | 'error'>('idle');
  const discover = () => {
    setStatus('discovering');
    void sitemapAuditApi
      .discover(values)
      .then((result) => {
        setCandidates(result.candidates.map((item) => item.normalized_url));
        setStatus('idle');
      })
      .catch(() => {
        setStatus('error');
      });
  };
  return (
    <>
      <Crumbs current="New audit" />
      <PageHeader eyebrow="Discover and compare" title="New sitemap audit">
        The server safely retrieves explicit, robots.txt, common-location, and nested-index
        sitemaps. Gzip sitemap decompression is not supported in Phase 21.
      </PageHeader>
      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setStatus('running');
            void sitemapAuditApi
              .create(values)
              .then((audit) => {
                void sitemapAuditApi.execute(audit.audit_id).catch(() => undefined);
                void navigate(`/sitemap-audits/${audit.audit_id}`);
              })
              .catch(() => {
                setStatus('error');
              });
          }}
        >
          <label htmlFor="sitemap-run">Completed crawl run ID</label>
          <input
            id="sitemap-run"
            required
            maxLength={64}
            value={values.runId}
            onChange={(event) => {
              setValues({ ...values, runId: event.target.value });
            }}
          />
          <label htmlFor="explicit-sitemap">Explicit sitemap URL (optional)</label>
          <input
            id="explicit-sitemap"
            type="url"
            maxLength={4096}
            placeholder="https://example.com/sitemap.xml"
            value={values.explicitSitemapUrl}
            onChange={(event) => {
              setValues({ ...values, explicitSitemapUrl: event.target.value });
            }}
          />
          <label>
            <input
              type="checkbox"
              checked={values.discoverRobots}
              onChange={(event) => {
                setValues({ ...values, discoverRobots: event.target.checked });
              }}
            />{' '}
            Discover robots.txt Sitemap directives
          </label>
          <label>
            <input
              type="checkbox"
              checked={values.discoverCommonLocations}
              onChange={(event) => {
                setValues({ ...values, discoverCommonLocations: event.target.checked });
              }}
            />{' '}
            Check common sitemap locations
          </label>
          <div className="export-actions">
            <Button type="button" disabled={!values.runId || status !== 'idle'} onClick={discover}>
              {status === 'discovering' ? 'Discovering…' : 'Preview discovery'}
            </Button>
            <Button disabled={!values.runId || status !== 'idle'}>
              {status === 'running' ? 'Running audit…' : 'Start sitemap audit'}
            </Button>
          </div>
          <div aria-live="polite">
            {status === 'error' ? (
              <Alert tone="error">
                The request failed. Confirm the run is completed and durable evidence is retained.
              </Alert>
            ) : null}
          </div>
        </form>
      </Card>
      {candidates.length ? (
        <Card>
          <h2>Discovered root candidates</h2>
          <ol>
            {candidates.map((candidate) => (
              <li className="wrap-anywhere" key={candidate}>
                {candidate}
              </li>
            ))}
          </ol>
        </Card>
      ) : null}
    </>
  );
}

function MetricGrid({ audit }: { audit: SitemapAudit }) {
  const values = [
    ['Documents', audit.document_count],
    ['Unique URLs', audit.unique_url_count],
    ['Add', audit.add_count],
    ['Remove', audit.remove_count],
    ['Review', audit.review_count],
    ['Unchanged', audit.unchanged_count],
  ];
  return (
    <div className="metric-grid">
      {values.map(([label, value]) => (
        <Card key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </Card>
      ))}
    </div>
  );
}

export function SitemapAuditDashboardPage() {
  const { auditId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const [refresh, setRefresh] = useState(0);
  const audit = useLoad(() => sitemapAuditApi.get(auditId), [auditId, refresh]);
  const comparisons = useLoad(
    () => sitemapAuditApi.comparisons(auditId, Object.fromEntries(params)),
    [auditId, params.toString(), refresh],
  );
  useEffect(() => {
    if (
      !audit.data ||
      [
        'completed',
        'completed_with_warnings',
        'partially_completed',
        'failed',
        'cancelled',
      ].includes(audit.data.state)
    )
      return;
    const timer = window.setInterval(() => {
      setRefresh((value) => value + 1);
    }, 1_000);
    return () => {
      window.clearInterval(timer);
    };
  }, [audit.data]);
  return (
    <>
      <Crumbs current="Dashboard" />
      <PageHeader eyebrow="Sitemap audit" title="Audit comparison">
        Add, Remove, Review, and Unchanged decisions from deterministic evidence precedence.
      </PageHeader>
      {!audit.data ? (
        <Loading error={audit.error} />
      ) : (
        <>
          <MetricGrid audit={audit.data} />
          <nav className="audit-tabs" aria-label="Sitemap audit inventory">
            <Link to="documents">Sitemap documents</Link>
            <Link to="entries">URL inventory</Link>
            <Link to="findings">Validation findings</Link>
          </nav>
          <div className="filter-bar">
            <label>
              Action
              <select
                value={params.get('action') ?? ''}
                onChange={(event) => {
                  const next = new URLSearchParams(params);
                  if (event.target.value) next.set('action', event.target.value);
                  else next.delete('action');
                  next.delete('cursor');
                  setParams(next);
                }}
              >
                <option value="">All</option>
                {actions.map((action) => (
                  <option key={action}>{action}</option>
                ))}
              </select>
            </label>
            <label>
              Search URL
              <input
                value={params.get('url') ?? ''}
                onChange={(event) => {
                  const next = new URLSearchParams(params);
                  if (event.target.value) next.set('url', event.target.value);
                  else next.delete('url');
                  next.delete('cursor');
                  setParams(next);
                }}
              />
            </label>
            <label>
              Reason code
              <input
                value={params.get('reason') ?? ''}
                onChange={(event) => {
                  const next = new URLSearchParams(params);
                  if (event.target.value) next.set('reason', event.target.value);
                  else next.delete('reason');
                  next.delete('cursor');
                  setParams(next);
                }}
              />
            </label>
          </div>
          {!comparisons.data ? (
            <Loading error={comparisons.error} />
          ) : comparisons.data.items.length === 0 ? (
            <EmptyState title="No comparison records match">Adjust the filters.</EmptyState>
          ) : (
            <>
              <TableFoundation>
                <caption>Sitemap comparison results</caption>
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>URL</th>
                    <th>State</th>
                    <th>Reason</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {comparisons.data.items.map((item) => (
                    <tr key={item.comparison_id}>
                      <td>{item.action}</td>
                      <td className="wrap-anywhere">{item.url}</td>
                      <td>{item.comparison_state}</td>
                      <td>{item.reason_code}</td>
                      <td>{item.http_status ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </TableFoundation>
              <Pager page={comparisons.data} />
            </>
          )}
          <SitemapExportActions auditId={auditId} />
        </>
      )}
    </>
  );
}

function Pager({ page }: { page: Page<unknown> }) {
  const [params, setParams] = useSearchParams();
  return (
    <nav className="pagination" aria-label="Pagination">
      <Button
        disabled={!page.next_cursor}
        onClick={() => {
          if (!page.next_cursor) return;
          const next = new URLSearchParams(params);
          next.set('cursor', page.next_cursor);
          setParams(next);
        }}
      >
        Next page
      </Button>
    </nav>
  );
}

function SitemapExportActions({ auditId }: { auditId: string }) {
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  return (
    <Card>
      <h2>Private exports</h2>
      <p>CSV, JSON, and Markdown exports are bounded and stored by the artifact service.</p>
      <div className="export-actions">
        {(['csv', 'json', 'markdown'] as const).map((format) => (
          <Button
            key={format}
            disabled={busy !== null}
            onClick={() => {
              setBusy(format);
              void sitemapAuditApi
                .export(auditId, format)
                .then((result) => {
                  const artifact = typeof result.artifact_id === 'string' ? result.artifact_id : '';
                  setMessage(`${format.toUpperCase()} ready${artifact ? `: ${artifact}` : ''}.`);
                })
                .catch(() => {
                  setMessage('Export failed; audit evidence remains intact.');
                })
                .finally(() => {
                  setBusy(null);
                });
            }}
          >
            {busy === format ? 'Creating…' : format.toUpperCase()}
          </Button>
        ))}
      </div>
      <p aria-live="polite">{message}</p>
    </Card>
  );
}

type InventoryKind = 'documents' | 'entries' | 'findings';
function InventoryPage({ kind }: { kind: InventoryKind }) {
  const { auditId = '' } = useParams();
  const [params] = useSearchParams();
  const state = useLoad(
    () => sitemapAuditApi[kind](auditId, Object.fromEntries(params)),
    [auditId, kind, params.toString()],
  );
  const columns = {
    documents: ['requested_url', 'discovery_source', 'depth', 'parse_state', 'entry_count'],
    entries: ['raw_location', 'validation_state', 'duplicate', 'is_child_reference'],
    findings: ['severity', 'code', 'safe_message', 'raw_url'],
  }[kind];
  return (
    <>
      <Crumbs auditId={auditId} current={kind} />
      <PageHeader title={kind.replace('_', ' ')}>
        Durable, bounded source evidence without raw XML response bodies.
      </PageHeader>
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title={`No ${kind}`}>No retained records are available.</EmptyState>
      ) : (
        <>
          <TableFoundation>
            <caption>Sitemap audit {kind}</caption>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{column.replaceAll('_', ' ')}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {state.data.items.map((item, index) => (
                <tr key={inventoryKey(item, index)}>
                  {columns.map((column) => (
                    <td className="wrap-anywhere" key={column}>
                      {displayValue(item[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </TableFoundation>
          <Pager page={state.data} />
        </>
      )}
    </>
  );
}

export const SitemapDocumentsPage = () => <InventoryPage kind="documents" />;
export const SitemapEntriesPage = () => <InventoryPage kind="entries" />;
export const SitemapFindingsPage = () => <InventoryPage kind="findings" />;

function inventoryKey(item: Record<string, unknown>, index: number) {
  for (const key of ['document_id', 'entry_id', 'finding_id']) {
    if (typeof item[key] === 'string') return item[key];
  }
  return String(index);
}

function displayValue(value: unknown) {
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value)
    : '—';
}
