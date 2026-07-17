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
import { linkAuditApi, type LinkQuery, type LinkValue } from '../link-audits/api';
import type {
  EvidenceStatus,
  LinkAudit,
  LinkExportFormat,
  LinkPage,
  LinkTarget,
} from '../link-audits/contracts';

const terminal = new Set(['completed', 'completed_with_warnings', 'failed', 'cancelled']);

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
        if (active) setState({ data: null, error: 'The link audit data could not be loaded.' });
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
    <ErrorState title="Link audit unavailable">{error}</ErrorState>
  ) : (
    <Card aria-busy="true">
      <Spinner label="Loading link audit" />
    </Card>
  );
}

function Crumbs({ auditId, current }: { auditId?: string; current: string }) {
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <Link to="/link-audits">Link Audits</Link>
      {auditId ? (
        <>
          <span aria-hidden="true">/</span>
          <Link to={`/link-audits/${auditId}`}>Audit</Link>
        </>
      ) : null}
      <span aria-hidden="true">/</span>
      <span aria-current="page">{current}</span>
    </nav>
  );
}

function AuditTabs({ auditId }: { auditId: string }) {
  return (
    <nav className="audit-tabs" aria-label="Link audit views">
      <Link to={`/link-audits/${auditId}`}>Summary</Link>
      <Link to={`/link-audits/${auditId}/targets`}>Targets</Link>
      <Link to={`/link-audits/${auditId}/occurrences`}>Occurrences</Link>
      <Link to={`/link-audits/${auditId}/chains`}>Redirect chains</Link>
      <Link to={`/link-audits/${auditId}/loops`}>Loops</Link>
      <Link to={`/link-audits/${auditId}/recommendations`}>Recommendations</Link>
      <Link to={`/link-audits/${auditId}/exports`}>Exports</Link>
    </nav>
  );
}

export function LinkAuditsPage() {
  const state = useLoad(() => linkAuditApi.list(), []);
  return (
    <>
      <PageHeader eyebrow="Durable crawl evidence" title="Link Audits">
        Review broken internal links, redirect chains, loops, impact, and evidence-backed fixes.
      </PageHeader>
      <p>
        <Link className="button" to="/link-audits/new">
          New link audit
        </Link>
      </p>
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No link audits">
          Choose a completed crawl run with durable page and source-link evidence.
        </EmptyState>
      ) : (
        <TableFoundation>
          <caption>Durable link audits</caption>
          <thead>
            <tr>
              <th>Site</th>
              <th>Run</th>
              <th>Status</th>
              <th>Links</th>
              <th>Broken</th>
              <th>Redirects</th>
              <th>Loops</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((audit) => (
              <tr key={audit.audit_id}>
                <td className="wrap-anywhere">
                  <Link to={`/link-audits/${audit.audit_id}`}>{audit.seed_url}</Link>
                </td>
                <td>{audit.run_id}</td>
                <td>
                  <StatusBadge tone={audit.state.startsWith('completed') ? 'positive' : 'neutral'}>
                    {audit.state.replaceAll('_', ' ')}
                  </StatusBadge>
                </td>
                <td>{audit.link_occurrence_count}</td>
                <td>{audit.broken_target_count}</td>
                <td>{audit.redirect_target_count}</td>
                <td>{audit.redirect_loop_count}</td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}

export function NewLinkAuditPage() {
  const navigate = useNavigate();
  const [runId, setRunId] = useState('');
  const [evidence, setEvidence] = useState<EvidenceStatus | null>(null);
  const [status, setStatus] = useState<'idle' | 'checking' | 'submitting' | 'error'>('idle');
  const check = () => {
    setStatus('checking');
    void linkAuditApi
      .evidence(runId)
      .then((value) => {
        setEvidence(value);
        setStatus('idle');
      })
      .catch(() => {
        setEvidence(null);
        setStatus('error');
      });
  };
  return (
    <>
      <Crumbs current="New audit" />
      <PageHeader eyebrow="Selected-run analysis" title="New link audit">
        The server builds the graph from durable parser-owned link, page, scope, and redirect
        evidence.
      </PageHeader>
      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setStatus('submitting');
            void linkAuditApi
              .create(runId)
              .then((audit) => {
                void linkAuditApi.execute(audit.audit_id).catch(() => undefined);
                void navigate(`/link-audits/${audit.audit_id}`);
              })
              .catch(() => {
                setStatus('error');
              });
          }}
        >
          <label htmlFor="link-audit-run">Completed crawl run ID</label>
          <input
            id="link-audit-run"
            required
            maxLength={64}
            value={runId}
            onChange={(event) => {
              setRunId(event.target.value);
              setEvidence(null);
            }}
          />
          <div className="export-actions">
            <Button type="button" disabled={!runId || status !== 'idle'} onClick={check}>
              {status === 'checking' ? 'Checking…' : 'Check evidence'}
            </Button>
            <Button disabled={!evidence?.compatible || status !== 'idle'}>
              {status === 'submitting' ? 'Starting…' : 'Start link audit'}
            </Button>
          </div>
        </form>
      </Card>
      {evidence ? (
        <Alert tone={evidence.compatible ? 'neutral' : 'warning'}>
          Page evidence: {evidence.page_evidence_count}; link occurrences:{' '}
          {evidence.link_evidence_count}; scope snapshot:{' '}
          {evidence.scope_available ? 'available' : 'missing'}.
        </Alert>
      ) : null}
      {status === 'error' ? (
        <Alert tone="error">
          The run is missing, incompatible, retained without evidence, or unavailable.
        </Alert>
      ) : null}
    </>
  );
}

function usePollingAudit(auditId: string) {
  const [audit, setAudit] = useState<LinkAudit | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const poll = () => {
      void linkAuditApi
        .get(auditId)
        .then((value) => {
          if (!active) return;
          setAudit(value);
          setError(null);
          if (!terminal.has(value.state)) timer = window.setTimeout(poll, 1_000);
        })
        .catch(() => {
          if (active) setError('The link audit status could not be refreshed.');
        });
    };
    poll();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [auditId]);
  return { audit, error };
}

export function LinkAuditDashboardPage() {
  const auditId = useParams().auditId ?? '';
  const { audit, error } = usePollingAudit(auditId);
  const summary = useLoad(() => linkAuditApi.summary(auditId), [auditId, audit?.state]);
  if (!audit) return <Loading error={error} />;
  const cards = [
    ['Occurrences', audit.link_occurrence_count],
    ['Unique targets', audit.target_count],
    ['Working', audit.working_target_count],
    ['Broken', audit.broken_target_count],
    ['Redirecting', audit.redirect_target_count],
    ['Unverified', audit.unverified_target_count],
    ['Chains', audit.redirect_chain_count],
    ['Loops', audit.redirect_loop_count],
    ['Recommendations', audit.recommendation_count],
  ] as const;
  return (
    <>
      <Crumbs auditId={auditId} current="Summary" />
      <PageHeader eyebrow="Broken links and redirects" title={audit.seed_url}>
        <StatusBadge tone={audit.state.startsWith('completed') ? 'positive' : 'neutral'}>
          {audit.state.replaceAll('_', ' ')}
        </StatusBadge>
      </PageHeader>
      <AuditTabs auditId={auditId} />
      {audit.state === 'failed' || audit.state === 'cancelled' ? (
        <Alert tone="error">
          The audit ended as {audit.state}. {audit.failure_code}
        </Alert>
      ) : null}
      <div className="metric-grid" aria-live="polite">
        {cards.map(([label, value]) => (
          <Card key={label}>
            <strong>{value}</strong>
            <span>{label}</span>
          </Card>
        ))}
      </div>
      {!summary.data && !terminal.has(audit.state) ? (
        <Alert tone="neutral">
          Analysis is running. This page will stop polling at a terminal state.
        </Alert>
      ) : null}
    </>
  );
}

function TargetTable({ page }: { page: LinkPage<LinkTarget> }) {
  return page.items.length === 0 ? (
    <EmptyState title="No matching targets">
      Adjust the filters or review another target state.
    </EmptyState>
  ) : (
    <TableFoundation>
      <caption>Link target analysis</caption>
      <thead>
        <tr>
          <th>Target</th>
          <th>State</th>
          <th>Status</th>
          <th>Severity</th>
          <th>Sources</th>
          <th>Occurrences</th>
          <th>Destination</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        {page.items.map((item) => (
          <tr key={item.target_id}>
            <td className="wrap-anywhere">{item.target_url}</td>
            <td>{item.broken_state.replaceAll('_', ' ')}</td>
            <td>{item.http_status ?? 'Unverified'}</td>
            <td>
              <StatusBadge tone={item.severity === 'critical' ? 'warning' : 'neutral'}>
                {item.severity}
              </StatusBadge>
            </td>
            <td>{item.unique_source_page_count}</td>
            <td>{item.total_occurrence_count}</td>
            <td className="wrap-anywhere">{item.final_target ?? '—'}</td>
            <td>{item.action.replaceAll('_', ' ')}</td>
          </tr>
        ))}
      </tbody>
    </TableFoundation>
  );
}

export function LinkTargetsPage() {
  const auditId = useParams().auditId ?? '';
  const [params, setParams] = useSearchParams();
  const query: LinkQuery = {
    broken_state: params.get('state'),
    severity: params.get('severity'),
    action: params.get('action'),
    url: params.get('q'),
    cursor: params.get('cursor'),
  };
  const state = useLoad(() => linkAuditApi.targets(auditId, query), [auditId, params.toString()]);
  return (
    <>
      <Crumbs auditId={auditId} current="Targets" />
      <PageHeader
        eyebrow="Target inventory"
        title="Broken, redirecting, unverified, and working targets"
      >
        Filter by URL, state, severity, or recommended action.
      </PageHeader>
      <AuditTabs auditId={auditId} />
      <Card>
        <form
          className="filter-bar"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const text = (name: string) => {
              const value = form.get(name);
              return typeof value === 'string' ? value : '';
            };
            setParams({
              q: text('q'),
              state: text('state'),
              severity: text('severity'),
              action: text('action'),
            });
          }}
        >
          <label htmlFor="target-search">Target URL</label>
          <input id="target-search" name="q" defaultValue={params.get('q') ?? ''} />
          <label htmlFor="target-state">State</label>
          <select id="target-state" name="state" defaultValue={params.get('state') ?? ''}>
            <option value="">All</option>
            <option value="broken_internal_link">Broken</option>
            <option value="redirecting_internal_link">Redirecting</option>
            <option value="unverified_internal_link">Unverified</option>
            <option value="working_internal_link">Working</option>
            <option value="external_link_not_audited">Ignored or external</option>
          </select>
          <label htmlFor="target-severity">Severity</label>
          <select id="target-severity" name="severity" defaultValue={params.get('severity') ?? ''}>
            <option value="">All</option>
            <option>critical</option>
            <option>high</option>
            <option>medium</option>
            <option>low</option>
            <option>info</option>
          </select>
          <label htmlFor="target-action">Action</label>
          <select id="target-action" name="action" defaultValue={params.get('action') ?? ''}>
            <option value="">All</option>
            <option value="fix_link">Fix link</option>
            <option value="update_link_to_final_destination">Update to final destination</option>
            <option value="remove_link">Remove link</option>
            <option value="replace_redirect">Replace redirect</option>
            <option value="review">Review</option>
          </select>
          <Button>Apply filters</Button>
        </form>
      </Card>
      {!state.data ? <Loading error={state.error} /> : <TargetTable page={state.data} />}
      {state.data?.next_cursor ? (
        <Button
          onClick={() => {
            setParams({ ...Object.fromEntries(params), cursor: state.data?.next_cursor ?? '' });
          }}
        >
          Next page
        </Button>
      ) : null}
    </>
  );
}

function GenericInventory({
  title,
  eyebrow,
  loader,
  columns,
}: {
  title: string;
  eyebrow: string;
  loader: (auditId: string) => Promise<LinkPage<LinkValue>>;
  columns: readonly [string, string][];
}) {
  const auditId = useParams().auditId ?? '';
  const state = useLoad(() => loader(auditId), [auditId]);
  return (
    <>
      <Crumbs auditId={auditId} current={title} />
      <PageHeader eyebrow={eyebrow} title={title}>
        Evidence is ordered deterministically and long URLs wrap.
      </PageHeader>
      <AuditTabs auditId={auditId} />
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title={`No ${title.toLowerCase()}`}>
          No matching records were produced.
        </EmptyState>
      ) : (
        <TableFoundation>
          <caption>{title}</caption>
          <thead>
            <tr>
              {columns.map(([label]) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((row, index) => (
              <tr key={rowKey(row, index)}>
                {columns.map(([label, key]) => (
                  <td className="wrap-anywhere" key={label}>
                    {formatValue(row[key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}

const formatValue = (value: unknown) => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value).replaceAll('_', ' ');
  }
  return '\u2014';
};

const rowKey = (row: LinkValue, index: number) => {
  const value = row.link_id ?? row.chain_id ?? row.recommendation_id;
  return typeof value === 'string' || typeof value === 'number' ? String(value) : String(index);
};

export function LinkOccurrencesPage() {
  return (
    <GenericInventory
      title="Link occurrences"
      eyebrow="Source-page evidence"
      loader={(id) => linkAuditApi.occurrences(id)}
      columns={[
        ['Source page', 'source_requested_url'],
        ['Target', 'resolved_url'],
        ['Raw href', 'raw_href'],
        ['Anchor', 'anchor_text'],
        ['Sequence', 'link_sequence'],
        ['Internal', 'internal'],
        ['Nofollow', 'nofollow'],
      ]}
    />
  );
}
export function RedirectChainsPage() {
  return (
    <GenericInventory
      title="Redirect chains"
      eyebrow="Ordered redirect evidence"
      loader={(id) => linkAuditApi.chains(id)}
      columns={[
        ['Entry', 'entry_url'],
        ['Ordered chain', 'nodes_json'],
        ['Final destination', 'final_url'],
        ['Hops', 'hop_count'],
        ['State', 'chain_state'],
        ['Severity', 'severity'],
        ['Occurrences', 'source_occurrence_count'],
      ]}
    />
  );
}
export function RedirectLoopsPage() {
  return (
    <GenericInventory
      title="Redirect loops"
      eyebrow="Cycle analysis"
      loader={(id) => linkAuditApi.loops(id)}
      columns={[
        ['Entry', 'entry_url'],
        ['Ordered cycle', 'nodes_json'],
        ['Severity', 'severity'],
        ['Source impact', 'source_occurrence_count'],
        ['Human review', 'loop'],
      ]}
    />
  );
}
export function LinkRecommendationsPage() {
  return (
    <GenericInventory
      title="Recommendations"
      eyebrow="Evidence-backed actions"
      loader={(id) => linkAuditApi.recommendations(id)}
      columns={[
        ['Source target', 'source_url'],
        ['Suggested destination', 'suggested_destination'],
        ['Action', 'action'],
        ['Confidence', 'confidence'],
        ['Reason', 'reason_code'],
        ['Severity', 'severity'],
        ['Occurrences', 'total_occurrence_count'],
        ['Human review', 'human_review_required'],
      ]}
    />
  );
}

export function LinkExportsPage() {
  const auditId = useParams().auditId ?? '';
  const state = useLoad(() => linkAuditApi.exports(auditId), [auditId]);
  const [message, setMessage] = useState<string | null>(null);
  const formats: readonly [LinkExportFormat, string][] = [
    ['broken_links_csv', 'Broken links CSV'],
    ['redirect_chains_csv', 'Redirect chains CSV'],
    ['redirect_map_csv', 'Redirect map CSV'],
    ['json', 'Complete JSON'],
    ['markdown', 'Markdown report'],
  ];
  return (
    <>
      <Crumbs auditId={auditId} current="Exports" />
      <PageHeader eyebrow="Artifact-backed outputs" title="Link audit exports">
        Generated files use existing authenticated artifact downloads and integrity checks.
      </PageHeader>
      <AuditTabs auditId={auditId} />
      <div className="export-actions">
        {formats.map(([format, label]) => (
          <Button
            key={format}
            onClick={() => {
              void linkAuditApi
                .export(auditId, format)
                .then(() => {
                  setMessage(`${label} created.`);
                })
                .catch(() => {
                  setMessage(`${label} could not be created.`);
                });
            }}
          >
            {label}
          </Button>
        ))}
      </div>
      {message ? <Alert tone="neutral">{message}</Alert> : null}
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.length === 0 ? (
        <EmptyState title="No exports">Choose an export format to create an artifact.</EmptyState>
      ) : (
        <ul>
          {state.data.map((item) => (
            <li key={String(item.export_id)}>
              {String(item.export_format)} — artifact {String(item.artifact_id)}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
