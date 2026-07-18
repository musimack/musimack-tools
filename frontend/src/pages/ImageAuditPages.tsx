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
import { imageAuditApi, type ImageAuditValue } from '../image-audits/api';

function useLoad<T>(factory: () => Promise<T>, dependencies: readonly unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    void factory()
      .then((result) => {
        if (active) setData(result);
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

const value = (item: ImageAuditValue, key: string) => {
  const raw = item[key];
  return typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean'
    ? String(raw)
    : '—';
};

function Loading({ error }: { error: boolean }) {
  return error ? (
    <ErrorState title="Image audit unavailable">Try again later.</ErrorState>
  ) : (
    <Card aria-busy="true">
      <Spinner label="Loading image audit" />
    </Card>
  );
}

export function ImageAuditsPage() {
  const { can } = useAuth();
  const state = useLoad(() => imageAuditApi.list(), []);
  return (
    <>
      <PageHeader eyebrow="Durable crawl evidence" title="Images & Alt Text">
        Review image resources, accessible alternatives, dimensions, loading, reuse, and impact.
      </PageHeader>
      {can('jobs.submit') ? (
        <p>
          <Link className="button" to="/image-audits/new">
            New image audit
          </Link>
        </p>
      ) : null}
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No image audits">
          Select a completed crawl with image evidence.
        </EmptyState>
      ) : (
        <TableFoundation>
          <caption>Image and alt-text audits</caption>
          <thead>
            <tr>
              <th>Source run</th>
              <th>Status</th>
              <th>Occurrences</th>
              <th>Unique images</th>
              <th>Broken</th>
              <th>Missing alt</th>
              <th>Recommendations</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((item) => (
              <tr key={value(item, 'audit_id')}>
                <td className="wrap-anywhere">
                  <Link to={`/image-audits/${value(item, 'audit_id')}`}>
                    {value(item, 'run_id')}
                  </Link>
                </td>
                <td>
                  <StatusBadge tone="neutral">{value(item, 'state')}</StatusBadge>
                </td>
                <td>{value(item, 'image_occurrence_count')}</td>
                <td>{value(item, 'unique_image_count')}</td>
                <td>{value(item, 'broken_image_count')}</td>
                <td>{value(item, 'missing_alt_count')}</td>
                <td>{value(item, 'recommendation_count')}</td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}

export function NewImageAuditPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [runId, setRunId] = useState('');
  const [evidence, setEvidence] = useState<ImageAuditValue | null>(null);
  const [error, setError] = useState(false);
  return (
    <>
      <PageHeader eyebrow="Server-resolved evidence" title="New image audit">
        The server uses retained page, scope, and parser-owned image evidence. No image URL list is
        accepted from the browser.
      </PageHeader>
      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void imageAuditApi
              .create(runId)
              .then((audit) => {
                const auditId = value(audit, 'audit_id');
                return imageAuditApi.execute(auditId).then(() => {
                  void navigate(`/image-audits/${auditId}`);
                });
              })
              .catch(() => {
                setError(true);
              });
          }}
        >
          <label htmlFor="image-audit-run">Completed crawl run ID</label>
          <input
            id="image-audit-run"
            required
            maxLength={64}
            value={runId}
            onChange={(event) => {
              setRunId(event.target.value);
              setEvidence(null);
            }}
          />
          <p>
            Internal images are verified through the bounded safe-fetch policy when retained
            evidence is unavailable. External images are not fetched by default.
          </p>
          <div className="export-actions">
            <Button
              type="button"
              disabled={!runId}
              onClick={() => {
                void imageAuditApi
                  .evidence(runId)
                  .then(setEvidence)
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
          Pages: {value(evidence, 'page_evidence_count')}; image occurrences:{' '}
          {value(evidence, 'image_evidence_count')}; scope: {value(evidence, 'scope_available')}.
        </Alert>
      ) : null}
      {error ? <Alert tone="error">The selected run is unavailable or incompatible.</Alert> : null}
    </>
  );
}

const tabs = [
  'resources',
  'occurrences',
  'broken',
  'redirecting',
  'alt-findings',
  'duplicate-groups',
  'pages',
  'dimensions',
  'loading',
  'recommendations',
  'exports',
];

function Tabs({ auditId }: { auditId: string }) {
  return (
    <nav className="audit-tabs" aria-label="Image audit views">
      <Link to={`/image-audits/${auditId}`}>Summary</Link>
      {tabs.map((name) => (
        <Link key={name} to={`/image-audits/${auditId}/${name}`}>
          {name.replaceAll('-', ' ')}
        </Link>
      ))}
    </nav>
  );
}

export function ImageAuditDashboardPage() {
  const auditId = useParams().auditId ?? '';
  const [refresh, setRefresh] = useState(0);
  const state = useLoad(() => imageAuditApi.summary(auditId), [auditId, refresh]);
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
  const summary = state.data;
  const metrics = [
    'state',
    'image_occurrence_count',
    'unique_image_count',
    'valid_image_count',
    'broken_image_count',
    'redirecting_image_count',
    'unverified_image_count',
    'missing_alt_count',
    'empty_alt_count',
    'generic_alt_count',
    'filename_alt_count',
    'duplicate_alt_count',
    'missing_dimensions_count',
    'loading_review_count',
    'recommendation_count',
  ];
  return (
    <>
      <PageHeader eyebrow="Conservative deterministic analysis" title="Image audit summary">
        Audit {auditId}
      </PageHeader>
      <Tabs auditId={auditId} />
      <div className="metric-grid">
        {metrics.map((metric) => (
          <Card key={metric}>
            <span>{metric.replaceAll('_', ' ')}</span>
            <strong>{value(summary, metric)}</strong>
          </Card>
        ))}
      </div>
      {value(summary, 'failure_code') !== '—' ? (
        <Alert tone="error">{value(summary, 'failure_code')}</Alert>
      ) : null}
    </>
  );
}

const columns: Record<string, string[]> = {
  resources: [
    'representative_url',
    'resource_state',
    'http_status',
    'content_type',
    'final_image_url',
    'unique_source_page_count',
    'total_occurrence_count',
    'sitewide_state',
    'missing_alt_count',
    'severity',
  ],
  occurrences: [
    'source_page_url',
    'image_url',
    'raw_src',
    'element_type',
    'alt_raw',
    'alt_state',
    'width_value',
    'height_value',
    'dimension_state',
    'loading_value',
    'decoding_value',
    'fetch_priority',
    'linked_image',
    'decorative',
    'occurrence_sequence',
    'severity',
  ],
  broken: [
    'representative_url',
    'http_status',
    'unique_source_page_count',
    'total_occurrence_count',
    'sitewide_state',
    'severity',
  ],
  redirecting: [
    'representative_url',
    'final_image_url',
    'http_status',
    'unique_source_page_count',
    'total_occurrence_count',
    'severity',
  ],
  'alt-findings': ['stable_code', 'severity', 'safe_message', 'context_json'],
  'duplicate-groups': [
    'group_type',
    'representative_alt',
    'image_count',
    'source_page_count',
    'occurrence_count',
    'severity',
    'sample_images_json',
    'sample_pages_json',
  ],
  pages: [
    'source_page_url',
    'image_occurrence_count',
    'unique_image_count',
    'missing_alt_count',
    'empty_alt_count',
    'broken_image_count',
    'redirecting_image_count',
    'missing_dimensions_count',
    'generic_alt_count',
    'severity',
  ],
  dimensions: ['stable_code', 'severity', 'safe_message', 'context_json'],
  loading: ['stable_code', 'severity', 'safe_message', 'context_json'],
  recommendations: [
    'source_page_url',
    'image_url',
    'action',
    'confidence',
    'severity',
    'reason_code',
    'human_review_state',
    'supporting_metrics_json',
  ],
};

export function ImageAuditInventoryPage() {
  const auditId = useParams().auditId ?? '';
  const resource = useParams().resource ?? 'resources';
  const [search, setSearch] = useState('');
  const [altSearch, setAltSearch] = useState('');
  const [severity, setSeverity] = useState('');
  const [resourceState, setResourceState] = useState('');
  const [altState, setAltState] = useState('');
  const [confidence, setConfidence] = useState('');
  const [filters, setFilters] = useState<Record<string, string | null>>({});
  const [cursor, setCursor] = useState<string | null>(null);
  const state = useLoad(
    () => imageAuditApi.resource(auditId, resource, { ...filters, cursor }),
    [auditId, resource, filters, cursor],
  );
  if (!state.data) return <Loading error={state.error} />;
  const selected = columns[resource] ?? columns.resources ?? [];
  const firstColumn = selected[0] ?? 'row';
  const supportsUrl = [
    'resources',
    'occurrences',
    'pages',
    'duplicate-groups',
    'recommendations',
  ].includes(resource);
  const supportsAlt = ['occurrences', 'duplicate-groups'].includes(resource);
  return (
    <>
      <PageHeader eyebrow="Evidence inventory" title={resource.replaceAll('-', ' ')}>
        Audit {auditId}
      </PageHeader>
      <Tabs auditId={auditId} />
      <Card>
        <form
          className="filter-grid"
          onSubmit={(event) => {
            event.preventDefault();
            setCursor(null);
            setFilters({
              url: supportsUrl ? search || null : null,
              alt: supportsAlt ? altSearch || null : null,
              severity: severity || null,
              resource_state: resource === 'resources' ? resourceState || null : null,
              alt_state: resource === 'occurrences' ? altState || null : null,
              confidence: resource === 'recommendations' ? confidence || null : null,
            });
          }}
        >
          {supportsUrl ? (
            <>
              <label htmlFor="image-url-search">Search URL</label>
              <input
                id="image-url-search"
                maxLength={512}
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                }}
              />
            </>
          ) : null}
          {supportsAlt ? (
            <>
              <label htmlFor="image-alt-search">Search alt text</label>
              <input
                id="image-alt-search"
                maxLength={1024}
                value={altSearch}
                onChange={(event) => {
                  setAltSearch(event.target.value);
                }}
              />
            </>
          ) : null}
          <label htmlFor="image-severity">Severity</label>
          <select
            id="image-severity"
            value={severity}
            onChange={(event) => {
              setSeverity(event.target.value);
            }}
          >
            <option value="">All severities</option>
            {['critical', 'high', 'medium', 'low', 'info'].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          {resource === 'resources' ? (
            <>
              <label htmlFor="image-resource-state">Resource state</label>
              <select
                id="image-resource-state"
                value={resourceState}
                onChange={(event) => {
                  setResourceState(event.target.value);
                }}
              >
                <option value="">All resource states</option>
                {[
                  'valid_image',
                  'broken_image',
                  'redirecting_image',
                  'unverified_image',
                  'external_image',
                  'out_of_scope_image',
                  'data_image',
                  'placeholder_image',
                  'unsupported_image_source',
                ].map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </>
          ) : null}
          {resource === 'occurrences' ? (
            <>
              <label htmlFor="image-alt-state">Alt state</label>
              <select
                id="image-alt-state"
                value={altState}
                onChange={(event) => {
                  setAltState(event.target.value);
                }}
              >
                <option value="">All alt states</option>
                {[
                  'alt_present',
                  'alt_missing',
                  'alt_empty',
                  'alt_generic',
                  'alt_filename_like',
                ].map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </>
          ) : null}
          {resource === 'recommendations' ? (
            <>
              <label htmlFor="image-confidence">Confidence</label>
              <select
                id="image-confidence"
                value={confidence}
                onChange={(event) => {
                  setConfidence(event.target.value);
                }}
              >
                <option value="">All confidence levels</option>
                {['high', 'medium', 'low'].map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </>
          ) : null}
          <Button>Apply filters</Button>
        </form>
      </Card>
      {state.data.items.length === 0 ? (
        <EmptyState title="No matching evidence">No records match this view.</EmptyState>
      ) : (
        <TableFoundation>
          <caption>{resource.replaceAll('-', ' ')} evidence</caption>
          <thead>
            <tr>
              {selected.map((column) => (
                <th key={column}>{column.replaceAll('_', ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((item, index) => (
              <tr key={`${value(item, firstColumn)}-${String(index)}`}>
                {selected.map((column) => (
                  <td className="wrap-anywhere" key={column}>
                    {value(item, column)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
      {state.data.next_cursor ? (
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

const exportFormats = [
  'image_inventory_csv',
  'alt_findings_csv',
  'broken_redirecting_images_csv',
  'duplicate_groups_csv',
  'page_summaries_csv',
  'recommendations_csv',
  'json',
  'markdown',
];

export function ImageAuditExportsPage() {
  const auditId = useParams().auditId ?? '';
  const { can } = useAuth();
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState(false);
  const state = useLoad(() => imageAuditApi.exports(auditId), [auditId, refresh]);
  if (!state.data) return <Loading error={state.error} />;
  return (
    <>
      <PageHeader eyebrow="Authenticated artifacts" title="Image audit exports">
        Exports are generated separately and retained through the existing artifact authority.
      </PageHeader>
      <Tabs auditId={auditId} />
      <div className="export-actions">
        {exportFormats.map((format) => (
          <Button
            key={format}
            disabled={!can('jobs.submit')}
            onClick={() => {
              void imageAuditApi
                .export(auditId, format)
                .then(() => {
                  setRefresh((current) => current + 1);
                })
                .catch(() => {
                  setError(true);
                });
            }}
          >
            {format.replaceAll('_', ' ')}
          </Button>
        ))}
      </div>
      {error ? <Alert tone="error">The export could not be created.</Alert> : null}
      {state.data.length === 0 ? (
        <EmptyState title="No exports">Create an export after analysis completes.</EmptyState>
      ) : (
        <TableFoundation>
          <caption>Image audit artifacts</caption>
          <thead>
            <tr>
              <th>Format</th>
              <th>State</th>
              <th>Rows</th>
              <th>Artifact</th>
            </tr>
          </thead>
          <tbody>
            {state.data.map((item) => (
              <tr key={value(item, 'export_id')}>
                <td>{value(item, 'export_format')}</td>
                <td>{value(item, 'state')}</td>
                <td>{value(item, 'row_count')}</td>
                <td>
                  <Link to={`/artifacts/${value(item, 'artifact_id')}`}>Download</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}
