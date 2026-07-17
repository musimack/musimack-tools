import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
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
import { internalLinkApi, type InternalLinkValue } from '../internal-links/api';

function useLoad<T>(factory: () => Promise<T>, dependencies: readonly unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    void factory()
      .then((value) => {
        if (active) setData(value);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);
  return { data, error };
}

function Loading({ error }: { error: boolean }) {
  return error ? (
    <ErrorState title="Internal-link analysis unavailable">Try again later.</ErrorState>
  ) : (
    <Card aria-busy="true">
      <Spinner label="Loading internal-link analysis" />
    </Card>
  );
}

const value = (item: InternalLinkValue, key: string) => {
  const raw = item[key];
  return typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean'
    ? String(raw)
    : '—';
};

export function InternalLinksPage() {
  const { can } = useAuth();
  const state = useLoad(() => internalLinkApi.list(), []);
  return (
    <>
      <PageHeader eyebrow="Durable crawl graph" title="Internal Links">
        Review reachability, orphan candidates, hubs, authorities, anchors, and opportunities.
      </PageHeader>
      {can('jobs.submit') ? (
        <p>
          <Link className="button" to="/internal-links/new">
            New internal-link analysis
          </Link>
        </p>
      ) : null}
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No internal-link analyses">
          Select a completed crawl with durable evidence.
        </EmptyState>
      ) : (
        <TableFoundation>
          <caption>Internal-link analyses</caption>
          <thead>
            <tr>
              <th>Site</th>
              <th>Run</th>
              <th>Status</th>
              <th>Pages</th>
              <th>Orphans</th>
              <th>Opportunities</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((item) => (
              <tr key={value(item, 'audit_id')}>
                <td className="wrap-anywhere">
                  <Link to={`/internal-links/${value(item, 'audit_id')}`}>
                    {value(item, 'seed_url')}
                  </Link>
                </td>
                <td>{value(item, 'run_id')}</td>
                <td>
                  <StatusBadge tone="neutral">{value(item, 'state')}</StatusBadge>
                </td>
                <td>{value(item, 'eligible_page_count')}</td>
                <td>{value(item, 'orphan_candidate_count')}</td>
                <td>{value(item, 'opportunity_count')}</td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}

export function NewInternalLinkPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [runId, setRunId] = useState('');
  const [evidence, setEvidence] = useState<InternalLinkValue | null>(null);
  const [error, setError] = useState(false);
  return (
    <>
      <PageHeader eyebrow="Server-resolved evidence" title="New internal-link analysis">
        Graph data is built only from retained crawl, scope, page, and source-link evidence.
      </PageHeader>
      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void internalLinkApi
              .create(runId)
              .then((audit) => {
                const auditId = value(audit, 'audit_id');
                void internalLinkApi.execute(auditId).catch(() => {
                  setError(true);
                });
                void navigate(`/internal-links/${auditId}`);
              })
              .catch(() => {
                setError(true);
              });
          }}
        >
          <label htmlFor="internal-link-run">Completed crawl run ID</label>
          <input
            id="internal-link-run"
            required
            maxLength={64}
            value={runId}
            onChange={(event) => {
              setRunId(event.target.value);
              setEvidence(null);
            }}
          />
          <div className="export-actions">
            <Button
              type="button"
              disabled={!runId}
              onClick={() => {
                void internalLinkApi
                  .evidence(runId)
                  .then((result) => {
                    setEvidence(result);
                  })
                  .catch(() => {
                    setError(true);
                  });
              }}
            >
              Check evidence
            </Button>
            <Button disabled={!evidence?.compatible || !can('jobs.submit')}>
              Create and execute
            </Button>
          </div>
        </form>
      </Card>
      {evidence ? (
        <Alert tone="neutral">
          Pages: {value(evidence, 'page_evidence_count')}; links:{' '}
          {value(evidence, 'link_evidence_count')}.
        </Alert>
      ) : null}
      {error ? <Alert tone="error">The selected run is unavailable or incompatible.</Alert> : null}
    </>
  );
}

const tabs = [
  'pages',
  'edges',
  'orphans',
  'hubs',
  'authorities',
  'reachability',
  'findings',
  'anchors',
  'opportunities',
  'exports',
];

const inventoryColumns: Record<string, string[]> = {
  pages: [
    'requested_url',
    'eligibility',
    'primary_state',
    'orphan_state',
    'severity',
    'inbound_occurrences',
    'outbound_occurrences',
    'graph_depth',
    'reachable',
  ],
  orphans: [
    'requested_url',
    'orphan_state',
    'inbound_occurrences',
    'redirect_adjusted_inlinks',
    'nofollow_inlinks',
    'reachable',
    'severity',
  ],
  hubs: [
    'requested_url',
    'hub_state',
    'unique_destination_pages',
    'outbound_occurrences',
    'broken_outlinks',
    'severity',
  ],
  authorities: [
    'requested_url',
    'authority_state',
    'unique_referring_pages',
    'inbound_occurrences',
    'sitewide_inlinks',
    'severity',
  ],
  edges: [
    'source_url',
    'target_url',
    'edge_state',
    'raw_occurrence_count',
    'nofollow_occurrence_count',
    'sitewide',
    'redirect_adjusted_identity',
    'canonical_adjusted_identity',
  ],
  reachability: [
    'page_identity',
    'seed_identity',
    'predecessor_identity',
    'distance',
    'reachable',
    'redirect_dependent',
    'nofollow_only',
  ],
  findings: ['stable_code', 'severity', 'safe_message', 'page_identity', 'edge_id'],
  anchors: [
    'target_url',
    'representative_anchor',
    'normalized_anchor',
    'anchor_state',
    'severity',
    'occurrence_count',
    'source_page_count',
    'share',
  ],
  opportunities: [
    'source_url',
    'target_url',
    'opportunity_type',
    'action',
    'confidence',
    'severity',
    'human_review_required',
    'reason_code',
  ],
};
function Tabs({ auditId }: { auditId: string }) {
  return (
    <nav className="audit-tabs" aria-label="Internal-link views">
      <Link to={`/internal-links/${auditId}`}>Summary</Link>
      {tabs.map((name) => (
        <Link key={name} to={`/internal-links/${auditId}/${name}`}>
          {name.replaceAll('_', ' ')}
        </Link>
      ))}
    </nav>
  );
}

export function InternalLinkDashboardPage() {
  const auditId = useParams().auditId ?? '';
  const [refresh, setRefresh] = useState(0);
  const state = useLoad(() => internalLinkApi.summary(auditId), [auditId, refresh]);
  useEffect(() => {
    const lifecycle = value(state.data ?? {}, 'state');
    if (
      !state.data ||
      ['completed', 'completed_with_warnings', 'failed', 'cancelled'].includes(lifecycle)
    )
      return;
    const timer = window.setInterval(() => {
      setRefresh((current) => current + 1);
    }, 1_000);
    return () => {
      window.clearInterval(timer);
    };
  }, [state.data]);
  if (!state.data) return <Loading error={state.error} />;
  return (
    <>
      <PageHeader eyebrow="Deterministic graph analysis" title="Internal-link summary">
        Audit {auditId}
      </PageHeader>
      <Tabs auditId={auditId} />
      <div className="metric-grid">
        {[
          'state',
          'eligible_page_count',
          'reachable_count',
          'orphan_candidate_count',
          'deep_page_count',
          'hub_candidate_count',
          'authority_candidate_count',
          'anchor_finding_count',
          'opportunity_count',
        ].map((key) => (
          <Card key={key}>
            <span>{key.replaceAll('_', ' ')}</span>
            <strong>{value(state.data ?? {}, key)}</strong>
          </Card>
        ))}
      </div>
    </>
  );
}

export function InternalLinkInventoryPage() {
  const auditId = useParams().auditId ?? '';
  const resource = useParams().resource ?? 'pages';
  const [urlSearch, setUrlSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [severity, setSeverity] = useState('');
  const [confidence, setConfidence] = useState('');
  const [appliedFilters, setAppliedFilters] = useState<Record<string, string | null>>({});
  const [cursor, setCursor] = useState<string | null>(null);
  const state = useLoad(
    () =>
      internalLinkApi.resource(auditId, resource, {
        url: appliedSearch,
        state: appliedFilters.state ?? null,
        severity: appliedFilters.severity ?? null,
        confidence: appliedFilters.confidence ?? null,
        cursor,
      }),
    [auditId, resource, appliedSearch, appliedFilters, cursor],
  );
  const items = state.data?.items ?? [];
  const keys = items.length
    ? (inventoryColumns[resource] ?? Object.keys(items[0] ?? {}).slice(0, 8)).filter(
        (key) => key in (items[0] ?? {}),
      )
    : [];
  return (
    <>
      <PageHeader eyebrow="Evidence inventory" title={resource.replaceAll('_', ' ')}>
        Bounded, cursor-paginated results.
      </PageHeader>
      <Tabs auditId={auditId} />
      <form
        className="filter-bar"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          setCursor(null);
          setAppliedSearch(urlSearch);
          setAppliedFilters({ state: stateFilter, severity, confidence });
        }}
      >
        <label htmlFor="internal-link-url-search">Search URL</label>
        <input
          id="internal-link-url-search"
          maxLength={512}
          value={urlSearch}
          onChange={(event) => {
            setUrlSearch(event.target.value);
          }}
        />
        <label htmlFor="internal-link-state">State</label>
        <input
          id="internal-link-state"
          maxLength={48}
          value={stateFilter}
          onChange={(event) => {
            setStateFilter(event.target.value);
          }}
        />
        <label htmlFor="internal-link-severity">Severity</label>
        <select
          id="internal-link-severity"
          value={severity}
          onChange={(event) => {
            setSeverity(event.target.value);
          }}
        >
          <option value="">Any</option>
          {['critical', 'high', 'medium', 'low', 'info'].map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <label htmlFor="internal-link-confidence">Confidence</label>
        <select
          id="internal-link-confidence"
          value={confidence}
          onChange={(event) => {
            setConfidence(event.target.value);
          }}
        >
          <option value="">Any</option>
          {['high', 'medium', 'low'].map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <Button>Apply filters</Button>
      </form>
      {!state.data ? (
        <Loading error={state.error} />
      ) : items.length === 0 ? (
        <EmptyState title="No results">No matching evidence.</EmptyState>
      ) : (
        <TableFoundation>
          <caption>{resource}</caption>
          <thead>
            <tr>
              {keys.map((key) => (
                <th key={key}>{key.replaceAll('_', ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={`${value(item, `${resource.slice(0, -1)}_id`)}-${String(index)}`}>
                {keys.map((key) => (
                  <td className="wrap-anywhere" key={key}>
                    {value(item, key)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
      {state.data?.next_cursor ? (
        <Button
          onClick={() => {
            setCursor(state.data?.next_cursor ?? null);
          }}
        >
          Next page
        </Button>
      ) : null}
    </>
  );
}

export function InternalLinkExportsPage() {
  const { can } = useAuth();
  const auditId = useParams().auditId ?? '';
  const state = useLoad(() => internalLinkApi.exports(auditId), [auditId]);
  const [message, setMessage] = useState<string | null>(null);
  const formats = [
    'page_metrics_csv',
    'orphan_candidates_csv',
    'hubs_authorities_csv',
    'anchor_findings_csv',
    'opportunities_csv',
    'json',
    'markdown',
  ];
  return (
    <>
      <PageHeader eyebrow="Artifact-backed outputs" title="Internal-link exports">
        Authenticated downloads use the existing artifact service.
      </PageHeader>
      <Tabs auditId={auditId} />
      <div className="export-actions">
        {formats.map((format) => (
          <Button
            key={format}
            disabled={!can('jobs.submit')}
            onClick={() => {
              setMessage(null);
              void internalLinkApi.export(auditId, format).then(
                () => {
                  setMessage(`${format.replaceAll('_', ' ')} created.`);
                },
                () => {
                  setMessage('Export creation failed.');
                },
              );
            }}
          >
            {format.replaceAll('_', ' ')}
          </Button>
        ))}
      </div>
      {message ? (
        <Alert tone={message.endsWith('failed.') ? 'error' : 'neutral'}>{message}</Alert>
      ) : null}
      {!state.data ? (
        <Loading error={state.error} />
      ) : (
        <ul>
          {state.data.map((item) => (
            <li key={value(item, 'export_id')}>
              {value(item, 'export_format')} — {value(item, 'artifact_id')}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
