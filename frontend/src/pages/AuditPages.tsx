import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { auditApi } from '../audits/api';
import { MetadataAuditRunSelector } from '../audits/RunSelector';
import type {
  Audit,
  AuditIssue,
  AuditPage,
  DuplicateGroup,
  ExportFormat,
  Page,
} from '../audits/contracts';
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

function useLoad<T>(factory: () => Promise<T>, dependencies: readonly unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({
    data: null,
    error: null,
  });
  useEffect(() => {
    const controller = new AbortController();
    void factory()
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, error: null });
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setState({ data: null, error: 'The audit data could not be loaded.' });
      });
    return () => {
      controller.abort();
    };
    // Endpoint factories intentionally follow route/query dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);
  return state;
}
function Crumbs({ auditId, current }: { auditId?: string; current: string }) {
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <Link to="/audits">Audits</Link>
      {auditId ? (
        <>
          <span aria-hidden="true">/</span>
          <Link to={`/audits/metadata/${auditId}`}>Metadata audit</Link>
        </>
      ) : null}
      <span aria-hidden="true">/</span>
      <span aria-current="page">{current}</span>
    </nav>
  );
}
function LoadingOrError({ error }: { error: string | null }) {
  return error ? (
    <ErrorState title="Audit unavailable">{error}</ErrorState>
  ) : (
    <Card aria-busy="true">
      <Spinner label="Loading audit" />
    </Card>
  );
}
function badge(value: string | null) {
  return (
    <StatusBadge
      tone={
        value === 'critical' || value === 'high'
          ? 'warning'
          : value === 'completed'
            ? 'positive'
            : 'neutral'
      }
    >
      {value ?? 'none'}
    </StatusBadge>
  );
}
export function AuditsPage() {
  const state = useLoad(() => auditApi.list(), []);
  return (
    <>
      <PageHeader eyebrow="Metadata quality" title="Audits">
        Create and review deterministic audits from durable crawl evidence.
      </PageHeader>
      <p>
        <Link className="button" to="/audits/metadata/new">
          New metadata audit
        </Link>
      </p>
      {!state.data ? (
        <LoadingOrError error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No metadata audits">
          Choose a terminal run with durable page evidence to begin.
        </EmptyState>
      ) : (
        <TableFoundation>
          <caption>Metadata audits</caption>
          <thead>
            <tr>
              <th>Audit</th>
              <th>Run</th>
              <th>State</th>
              <th>Pages</th>
              <th>Issues</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((item) => (
              <tr key={item.audit_id}>
                <td>
                  <Link to={`/audits/metadata/${item.audit_id}`}>{item.audit_id}</Link>
                </td>
                <td>{item.run_id}</td>
                <td>{badge(item.state)}</td>
                <td>{item.page_count}</td>
                <td>{item.issue_count}</td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}
export function NewAuditPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const runId = params.get('run') ?? '';
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<'idle' | 'running' | 'error'>('idle');
  const candidates = useLoad(() => auditApi.runCandidates(), []);
  useEffect(() => {
    if (!candidates.data || runId) return;
    const eligible = candidates.data.filter((candidate) => candidate.eligible);
    const sites = new Set(eligible.map((candidate) => candidate.seed_url));
    const mostRecent = eligible[0];
    if (mostRecent && sites.size === 1) {
      const next = new URLSearchParams(params);
      next.set('run', mostRecent.run_id);
      setParams(next, { replace: true });
    }
  }, [candidates.data, params, runId, setParams]);
  const selected = candidates.data?.find((candidate) => candidate.run_id === runId);
  return (
    <>
      <Crumbs current="New audit" />
      <PageHeader eyebrow="Create" title="New metadata audit">
        Audit an existing terminal run. Thresholds are server-managed heuristics: titles 20–60 and
        descriptions 70–160 characters.
      </PageHeader>
      <Card>
        {!candidates.data ? (
          candidates.error ? (
            <ErrorState title="Crawl runs unavailable">{candidates.error}</ErrorState>
          ) : (
            <Spinner label="Loading completed crawl runs" />
          )
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (status === 'running' || !selected?.eligible) return;
              setStatus('running');
              void auditApi
                .create(runId)
                .then((item) => {
                  void navigate(`/audits/metadata/${item.audit_id}`);
                })
                .catch(() => {
                  setStatus('error');
                });
            }}
          >
            <MetadataAuditRunSelector
              candidates={candidates.data}
              selectedRunId={runId}
              search={search}
              onSearch={setSearch}
              onSelect={(value) => {
                const next = new URLSearchParams(params);
                next.set('run', value);
                setParams(next, { replace: true });
              }}
            />
            {runId && !selected ? (
              <Alert tone="error">
                The selected run is unavailable, deleted, or no longer retained. Choose another
                completed crawl.
              </Alert>
            ) : null}
            <p>
              Categories: title, meta description, canonical, robots, indexability, status, and
              content type.
            </p>
            <Button disabled={status === 'running' || !selected?.eligible}>
              {status === 'running' ? 'Running audit…' : 'Run Metadata Audit'}
            </Button>
            <div aria-live="polite">
              {status === 'error' ? (
                <Alert tone="error">
                  Creation failed. Confirm the run is terminal and page evidence is available.
                </Alert>
              ) : null}
            </div>
          </form>
        )}
      </Card>
    </>
  );
}
function Metrics({ summary }: { summary: Record<string, unknown> }) {
  const values = [
    ['Total pages', summary.total_pages],
    ['Audited HTML', summary.audited_html_pages],
    ['Pages with issues', summary.pages_with_issues],
    ['Total issues', summary.total_issues],
    ['Partial pages', summary.partial_page_count],
    ['Failed pages', summary.failed_page_count],
  ];
  return (
    <div className="metric-grid">
      {values.map(([label, value]) => (
        <Card key={String(label)}>
          <span>{String(label)}</span>
          <strong>{typeof value === 'number' ? value : 'Unavailable'}</strong>
        </Card>
      ))}
    </div>
  );
}
export function AuditDashboardPage() {
  const { auditId = '' } = useParams();
  const audit = useLoad(() => auditApi.get(auditId), [auditId]);
  const summary = useLoad(() => auditApi.summary(auditId), [auditId]);
  return (
    <>
      <Crumbs current="Dashboard" />
      <PageHeader eyebrow="Metadata audit" title="Audit dashboard">
        Server-calculated findings from durable page evidence.
      </PageHeader>
      {!audit.data || !summary.data ? (
        <LoadingOrError error={audit.error ?? summary.error} />
      ) : (
        <>
          <Card>
            <dl className="detail-list">
              <div>
                <dt>Audit ID</dt>
                <dd>{audit.data.audit_id}</dd>
              </div>
              <div>
                <dt>State</dt>
                <dd>{badge(audit.data.state)}</dd>
              </div>
              <div>
                <dt>Job</dt>
                <dd>{audit.data.job_id}</dd>
              </div>
              <div>
                <dt>Run</dt>
                <dd>{audit.data.run_id}</dd>
              </div>
              <div>
                <dt>Seed</dt>
                <dd className="wrap-anywhere">{audit.data.seed_url}</dd>
              </div>
              <div>
                <dt>Partial</dt>
                <dd>{String(audit.data.partial)}</dd>
              </div>
            </dl>
          </Card>
          <Metrics summary={summary.data} />
          <nav className="audit-tabs" aria-label="Audit views">
            <Link to="pages">Pages</Link>
            <Link to="issues">Issues</Link>
            <Link to="duplicates">Duplicates</Link>
          </nav>
          <Distribution title="Severity" value={summary.data.severity_counts} />
          <Distribution title="Categories" value={summary.data.category_counts} />
          <ExportActions audit={audit.data} />
        </>
      )}
    </>
  );
}
function Distribution({ title, value }: { title: string; value: unknown }) {
  const entries =
    typeof value === 'object' && value !== null && !Array.isArray(value)
      ? Object.entries(value)
      : [];
  return (
    <Card>
      <h2>{title}</h2>
      {entries.length ? (
        <dl className="distribution-list">
          {entries.map(([key, count]) => (
            <div key={key}>
              <dt>{key.replaceAll('_', ' ')}</dt>
              <dd>{String(count)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>Unavailable</p>
      )}
    </Card>
  );
}
function ExportActions({ audit }: { audit: Audit }) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [message, setMessage] = useState('');
  return (
    <Card>
      <h2>Exports</h2>
      <p>
        Exports are backend-generated, bounded to 100,000 rows, and registered as private artifacts.
      </p>
      <div className="export-actions">
        {(['csv', 'json', 'markdown'] as const).map((format) => (
          <Button
            key={format}
            disabled={busy !== null || !audit.export_available}
            onClick={() => {
              setBusy(format);
              void auditApi
                .export(audit.audit_id, format)
                .then(() => {
                  setMessage(`${format.toUpperCase()} export is available in Artifacts.`);
                })
                .catch(() => {
                  setMessage('Export failed; the audit remains intact.');
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
function Filter({
  name,
  label,
  options,
}: {
  name: string;
  label: string;
  options: readonly string[];
}) {
  const [params, setParams] = useSearchParams();
  return (
    <label>
      {label}
      <select
        value={params.get(name) ?? ''}
        onChange={(event) => {
          const next = new URLSearchParams(params);
          if (event.target.value) next.set(name, event.target.value);
          else next.delete(name);
          next.delete('cursor');
          setParams(next);
        }}
      >
        <option value="">All</option>
        {options.map((value) => (
          <option key={value}>{value}</option>
        ))}
      </select>
    </label>
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
export function AuditPagesPage() {
  const { auditId = '' } = useParams();
  const [params] = useSearchParams();
  const state = useLoad(
    () => auditApi.pages(auditId, Object.fromEntries(params)),
    [auditId, params.toString()],
  );
  return (
    <>
      <Crumbs auditId={auditId} current="Pages" />
      <PageHeader title="Page inventory">
        Bounded page projections and audit-specific findings.
      </PageHeader>
      <div className="filter-bar">
        <Filter
          name="content_type"
          label="Content type"
          options={[
            'html',
            'pdf',
            'image',
            'json',
            'plain_text',
            'xml',
            'other',
            'ambiguous',
            'missing',
          ]}
        />
        <Filter
          name="indexability"
          label="Indexability"
          options={['available', 'conflicting', 'unavailable']}
        />
        <Filter
          name="highest_severity"
          label="Severity"
          options={['critical', 'high', 'medium', 'low', 'information']}
        />
      </div>
      {!state.data ? (
        <LoadingOrError error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No pages match">Adjust the filters to see more pages.</EmptyState>
      ) : (
        <>
          <TableFoundation>
            <caption>Audited pages</caption>
            <thead>
              <tr>
                <th>URL</th>
                <th>Status</th>
                <th>Content</th>
                <th>Title</th>
                <th>Issues</th>
                <th>Severity</th>
              </tr>
            </thead>
            <tbody>
              {state.data.items.map((item) => (
                <tr key={item.audit_page_id}>
                  <td className="wrap-anywhere">
                    <Link to={item.audit_page_id}>{item.url}</Link>
                  </td>
                  <td>{item.http_status ?? '—'}</td>
                  <td>{item.content_type_category}</td>
                  <td>{item.title_value ?? item.title_presence}</td>
                  <td>{item.issue_count}</td>
                  <td>{badge(item.highest_severity)}</td>
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
export function AuditIssuesPage() {
  const { auditId = '' } = useParams();
  const [params] = useSearchParams();
  const state = useLoad(
    () => auditApi.issues(auditId, Object.fromEntries(params)),
    [auditId, params.toString()],
  );
  return (
    <>
      <Crumbs auditId={auditId} current="Issues" />
      <PageHeader title="Issues">Operational prioritization, not a ranking score.</PageHeader>
      <div className="filter-bar">
        <Filter
          name="severity"
          label="Severity"
          options={['critical', 'high', 'medium', 'low', 'information']}
        />
        <Filter
          name="category"
          label="Category"
          options={[
            'title',
            'meta_description',
            'canonical',
            'robots',
            'indexability',
            'status',
            'content_type',
          ]}
        />
      </div>
      {!state.data ? (
        <LoadingOrError error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No issues match">The current filters returned no findings.</EmptyState>
      ) : (
        <>
          <IssueTable items={state.data.items} />
          <Pager page={state.data} />
        </>
      )}
    </>
  );
}
function IssueTable({ items }: { items: AuditIssue[] }) {
  return (
    <TableFoundation>
      <caption>Metadata audit issues</caption>
      <thead>
        <tr>
          <th>Severity</th>
          <th>Code</th>
          <th>URL</th>
          <th>Summary</th>
          <th>Determinacy</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.issue_id}>
            <td>{badge(item.severity)}</td>
            <td>
              <code>{item.code}</code>
            </td>
            <td className="wrap-anywhere">{item.url}</td>
            <td>{item.summary}</td>
            <td>{item.determinacy}</td>
          </tr>
        ))}
      </tbody>
    </TableFoundation>
  );
}
export function AuditPageDetailPage() {
  const { auditId = '', pageId = '' } = useParams();
  const state = useLoad(() => auditApi.page(auditId, pageId), [auditId, pageId]);
  const page = state.data?.page as AuditPage | undefined;
  const issues = (state.data?.issues ?? []) as AuditIssue[];
  const safeUrl = page?.url && /^https?:\/\//iu.test(page.url) ? page.url : null;
  return (
    <>
      <Crumbs auditId={auditId} current="Page evidence" />
      <PageHeader title="Page evidence">
        Durable crawl evidence; raw HTML and headers are never displayed.
      </PageHeader>
      {!page ? (
        <LoadingOrError error={state.error} />
      ) : (
        <>
          <Card>
            <dl className="detail-list">
              {Object.entries(page)
                .filter(([key]) => !key.includes('identity'))
                .map(([key, value]) => (
                  <div key={key}>
                    <dt>{key.replaceAll('_', ' ')}</dt>
                    <dd className="wrap-anywhere">
                      {value === null ? 'Unavailable' : String(value)}
                    </dd>
                  </div>
                ))}
            </dl>
            <div className="export-actions">
              <Button onClick={() => void navigator.clipboard.writeText(page.url)}>Copy URL</Button>
              {safeUrl ? (
                <a href={safeUrl} target="_blank" rel="noopener noreferrer">
                  Open page (external)
                </a>
              ) : null}
            </div>
          </Card>
          <IssueTable items={issues} />
        </>
      )}
    </>
  );
}
export function AuditDuplicatesPage() {
  const { auditId = '' } = useParams();
  const [params] = useSearchParams();
  const state = useLoad(
    () => auditApi.duplicates(auditId, Object.fromEntries(params)),
    [auditId, params.toString()],
  );
  return (
    <>
      <Crumbs auditId={auditId} current="Duplicates" />
      <PageHeader title="Duplicate groups">
        Exact Unicode-normalized groups; no fuzzy matching.
      </PageHeader>
      <Filter name="duplicate_type" label="Type" options={['title', 'meta_description']} />
      {!state.data ? (
        <LoadingOrError error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No duplicate groups">
          No non-empty exact duplicates were found.
        </EmptyState>
      ) : (
        <>
          <TableFoundation>
            <caption>Duplicate metadata groups</caption>
            <thead>
              <tr>
                <th>Type</th>
                <th>Sample</th>
                <th>Members</th>
              </tr>
            </thead>
            <tbody>
              {state.data.items.map((group) => (
                <tr key={group.group_id}>
                  <td>
                    <Link to={group.group_id}>{group.duplicate_type}</Link>
                  </td>
                  <td>{group.sample_value}</td>
                  <td>{group.member_count}</td>
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
export function AuditDuplicateDetailPage() {
  const { auditId = '', groupId = '' } = useParams();
  const state = useLoad(() => auditApi.duplicate(auditId, groupId), [auditId, groupId]);
  const group = state.data?.group as DuplicateGroup | undefined;
  const members = (state.data?.members ?? []) as AuditPage[];
  return (
    <>
      <Crumbs auditId={auditId} current="Duplicate group" />
      <PageHeader title="Duplicate group">
        Unicode NFKC, trimmed and collapsed whitespace, then Unicode case-folding; punctuation and
        stop words remain.
      </PageHeader>
      {!group ? (
        <LoadingOrError error={state.error} />
      ) : (
        <Card>
          <h2>{group.duplicate_type.replace('_', ' ')}</h2>
          <p>{group.sample_value}</p>
          <p>{group.member_count} members</p>
          <ul>
            {members.map((member) => (
              <li key={member.audit_page_id}>
                <Link to={`/audits/metadata/${auditId}/pages/${member.audit_page_id}`}>
                  {member.url}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
