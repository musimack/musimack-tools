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
import { structuredDataAuditApi, type StructuredDataValue } from '../structured-data-audits/api';

const resources = [
  'blocks',
  'entities',
  'properties',
  'pages',
  'parse-findings',
  'consistency-findings',
  'duplicate-groups',
  'profiles',
  'recommendations',
] as const;

const exportFormats = [
  'structured_data_inventory_csv',
  'entity_inventory_csv',
  'property_findings_csv',
  'duplicate_groups_csv',
  'page_summaries_csv',
  'recommendations_csv',
  'json',
  'markdown',
] as const;

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

const value = (item: StructuredDataValue, key: string) => {
  const raw = item[key];
  return typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean'
    ? String(raw)
    : '—';
};
const boundedValue = (item: StructuredDataValue, key: string) => {
  const rendered = value(item, key);
  return rendered.length > 512 ? `${rendered.slice(0, 500)}… [truncated]` : rendered;
};

function Loading({ error }: { error: boolean }) {
  return error ? (
    <ErrorState title="Structured-data audit unavailable">Try again later.</ErrorState>
  ) : (
    <Card aria-busy="true">
      <Spinner label="Loading structured-data audit" />
    </Card>
  );
}

function Tabs({ auditId }: { auditId: string }) {
  return (
    <nav className="audit-tabs" aria-label="Structured-data audit views">
      <Link to={`/structured-data-audits/${auditId}`}>Summary</Link>
      {resources.map((name) => (
        <Link key={name} to={`/structured-data-audits/${auditId}/${name}`}>
          {name.replaceAll('-', ' ')}
        </Link>
      ))}
      <Link to={`/structured-data-audits/${auditId}/exports`}>exports</Link>
    </nav>
  );
}

export function StructuredDataAuditsPage() {
  const { can } = useAuth();
  const state = useLoad(() => structuredDataAuditApi.list(), []);
  return (
    <>
      <PageHeader eyebrow="Retained crawl evidence" title="Structured Data">
        Inventory and review JSON-LD, Microdata, RDFa, entities, profiles, and consistency.
      </PageHeader>
      {can('jobs.submit') ? (
        <p>
          <Link className="button" to="/structured-data-audits/new">
            New structured-data audit
          </Link>
        </p>
      ) : null}
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No structured-data audits">Select a completed crawl run.</EmptyState>
      ) : (
        <TableFoundation>
          <caption>Structured-data audits</caption>
          <thead>
            <tr>
              <th>Source run</th>
              <th>Status</th>
              <th>Pages</th>
              <th>Blocks</th>
              <th>Entities</th>
              <th>Findings</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((item) => (
              <tr key={value(item, 'audit_id')}>
                <td className="wrap-anywhere">
                  <Link to={`/structured-data-audits/${value(item, 'audit_id')}`}>
                    {value(item, 'run_id')}
                  </Link>
                </td>
                <td>
                  <StatusBadge tone="neutral">{value(item, 'state')}</StatusBadge>
                </td>
                <td>{value(item, 'total_pages')}</td>
                <td>{value(item, 'total_blocks')}</td>
                <td>{value(item, 'total_entities')}</td>
                <td>{value(item, 'total_findings')}</td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}

export function NewStructuredDataAuditPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [runId, setRunId] = useState('');
  const [evidence, setEvidence] = useState<StructuredDataValue | null>(null);
  const [error, setError] = useState(false);
  return (
    <>
      <PageHeader eyebrow="Server-resolved evidence" title="New structured-data audit">
        The server analyzes bounded evidence retained by the crawl parser; no markup is executed.
      </PageHeader>
      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void structuredDataAuditApi
              .create(runId)
              .then((audit) => {
                const auditId = value(audit, 'audit_id');
                return structuredDataAuditApi.execute(auditId).then(() => {
                  void navigate(`/structured-data-audits/${auditId}`);
                });
              })
              .catch(() => {
                setError(true);
              });
          }}
        >
          <label htmlFor="structured-data-run">Completed crawl run ID</label>
          <input
            id="structured-data-run"
            required
            maxLength={64}
            value={runId}
            onChange={(event) => {
              setRunId(event.target.value);
              setEvidence(null);
            }}
          />
          <p>Profile observations are versioned, explainable, and non-certifying.</p>
          <div className="export-actions">
            <Button
              type="button"
              disabled={!runId}
              onClick={() => {
                void structuredDataAuditApi
                  .evidence(runId)
                  .then(setEvidence)
                  .catch(() => {
                    setError(true);
                  });
              }}
            >
              Check evidence
            </Button>
            <Button disabled={!evidence?.ready || !can('jobs.submit')}>Create and execute</Button>
          </div>
        </form>
      </Card>
      {evidence ? (
        <Alert tone="neutral">
          Pages: {value(evidence, 'page_count')}; blocks: {value(evidence, 'block_count')}.
        </Alert>
      ) : null}
      {error ? <Alert tone="error">The selected run is unavailable or incompatible.</Alert> : null}
    </>
  );
}

export function StructuredDataAuditDashboardPage() {
  const auditId = useParams().auditId ?? '';
  const [refresh, setRefresh] = useState(0);
  const state = useLoad(() => structuredDataAuditApi.summary(auditId), [auditId, refresh]);
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
  return (
    <>
      <PageHeader eyebrow="Structured-data audit" title="Audit summary">
        Deterministic syntax, entity, property, profile, duplicate, and consistency observations.
      </PageHeader>
      <Tabs auditId={auditId} />
      {!state.data ? (
        <Loading error={state.error} />
      ) : (
        <>
          <Alert tone="neutral">
            This audit is review evidence only and does not certify search-engine eligibility.
          </Alert>
          <TableFoundation>
            <caption>Audit totals</caption>
            <tbody>
              {[
                'state',
                'total_pages',
                'total_blocks',
                'total_entities',
                'total_findings',
                'warning_count',
                'profile_version',
              ].map((key) => (
                <tr key={key}>
                  <th>{key.replaceAll('_', ' ')}</th>
                  <td>{value(state.data ?? {}, key)}</td>
                </tr>
              ))}
            </tbody>
          </TableFoundation>
        </>
      )}
    </>
  );
}

export function StructuredDataAuditInventoryPage() {
  const auditId = useParams().auditId ?? '';
  const resource = useParams().resource ?? 'blocks';
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [severity, setSeverity] = useState('');
  const [confidence, setConfidence] = useState('');
  const [observationState, setObservationState] = useState('');
  const [format, setFormat] = useState('');
  const [cursor, setCursor] = useState<string | null>(null);
  const state = useLoad(
    () =>
      structuredDataAuditApi.resource(auditId, resource, {
        search: appliedSearch || null,
        severity: severity || null,
        confidence: confidence || null,
        observation_state: observationState || null,
        format: format || null,
        cursor,
        page_size: '20',
      }),
    [auditId, resource, appliedSearch, severity, confidence, observationState, format, cursor],
  );
  return (
    <>
      <PageHeader eyebrow="Structured-data audit" title={resource.replaceAll('-', ' ')}>
        Bounded, paginated retained evidence and derived observations.
      </PageHeader>
      <Tabs auditId={auditId} />
      <Card>
        <form
          className="filter-grid"
          onSubmit={(event) => {
            event.preventDefault();
            setCursor(null);
            setAppliedSearch(search.trim());
          }}
        >
          <label htmlFor="structured-data-search">Search retained evidence</label>
          <input
            id="structured-data-search"
            maxLength={512}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
            }}
          />
          <label htmlFor="structured-data-severity">Severity</label>
          <select
            id="structured-data-severity"
            value={severity}
            onChange={(event) => {
              setCursor(null);
              setSeverity(event.target.value);
            }}
          >
            <option value="">All severities</option>
            <option value="error">Error</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
          <label htmlFor="structured-data-confidence">Confidence</label>
          <select
            id="structured-data-confidence"
            value={confidence}
            onChange={(event) => {
              setCursor(null);
              setConfidence(event.target.value);
            }}
          >
            <option value="">All confidence levels</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
            <option value="indeterminate">Indeterminate</option>
          </select>
          <label htmlFor="structured-data-profile-state">Profile state</label>
          <select
            id="structured-data-profile-state"
            value={observationState}
            onChange={(event) => {
              setCursor(null);
              setObservationState(event.target.value);
            }}
          >
            <option value="">All profile states</option>
            {[
              'present',
              'missing',
              'empty',
              'invalid',
              'conflicting',
              'not_applicable',
              'indeterminate',
            ].map((stateName) => (
              <option key={stateName} value={stateName}>
                {stateName.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
          <label htmlFor="structured-data-format">Format</label>
          <select
            id="structured-data-format"
            value={format}
            onChange={(event) => {
              setCursor(null);
              setFormat(event.target.value);
            }}
          >
            <option value="">All formats</option>
            <option value="json_ld">JSON-LD</option>
            <option value="microdata">Microdata</option>
            <option value="rdfa">RDFa</option>
          </select>
          <Button>Apply filters</Button>
        </form>
      </Card>
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No records">No matching observations were produced.</EmptyState>
      ) : (
        <TableFoundation>
          <caption>{resource.replaceAll('-', ' ')}</caption>
          <thead>
            <tr>
              <th>Page or entity</th>
              <th>Classification</th>
              <th>Details</th>
              <th>Confidence</th>
              <th>Human review</th>
              <th>Scope and counts</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((item, index) => (
              <tr key={value(item, 'id') === '—' ? String(index) : value(item, 'id')}>
                <td className="wrap-anywhere">
                  {value(item, 'page_url') !== '—'
                    ? value(item, 'page_url')
                    : value(item, 'entity_id')}
                </td>
                <td>
                  {['code', 'entity_type', 'property_name', 'profile_name', 'action', 'format']
                    .map((key) => value(item, key))
                    .find((entry) => entry !== '—') ?? '—'}
                </td>
                <td>{value(item, 'confidence')}</td>
                <td>{value(item, 'requires_human_review')}</td>
                <td>
                  {value(item, 'scope')} / {value(item, 'occurrence_count')} occurrences /{' '}
                  {value(item, 'affected_page_count')} pages
                </td>
                <td>
                  {[
                    'explanation',
                    'observation_state',
                    'parse_status',
                    'value_state',
                    'value_json',
                    'supporting_evidence_json',
                  ]
                    .map((key) => boundedValue(item, key))
                    .find((entry) => entry !== '—') ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
      {state.data?.next_cursor ? (
        <p>
          <Button
            onClick={() => {
              setCursor(state.data?.next_cursor ?? null);
            }}
          >
            Next page
          </Button>
        </p>
      ) : null}
    </>
  );
}

export function StructuredDataAuditExportsPage() {
  const auditId = useParams().auditId ?? '';
  const { can } = useAuth();
  const [created, setCreated] = useState<StructuredDataValue[]>([]);
  const [exportError, setExportError] = useState(false);
  const state = useLoad(() => structuredDataAuditApi.exports(auditId), [auditId, created.length]);
  return (
    <>
      <PageHeader eyebrow="Structured-data audit" title="Exports">
        Create bounded CSV, JSON, or Markdown review artifacts.
      </PageHeader>
      <Tabs auditId={auditId} />
      {can('jobs.submit') ? (
        <div className="export-actions">
          {exportFormats.map((format) => (
            <Button
              key={format}
              onClick={() => {
                setExportError(false);
                void structuredDataAuditApi
                  .export(auditId, format)
                  .then((item) => {
                    setCreated((current) => [...current, item]);
                  })
                  .catch(() => {
                    setExportError(true);
                  });
              }}
            >
              {format.replaceAll('_', ' ')}
            </Button>
          ))}
        </div>
      ) : (
        <Alert tone="neutral">
          Viewer access is read-only; existing downloads remain available.
        </Alert>
      )}
      {exportError ? (
        <Alert tone="error">
          The export could not be created. Existing artifacts were not changed.
        </Alert>
      ) : null}
      {!state.data ? (
        <Loading error={state.error} />
      ) : (
        <TableFoundation>
          <caption>Created exports</caption>
          <thead>
            <tr>
              <th>Format</th>
              <th>Filename</th>
              <th>Media type</th>
            </tr>
          </thead>
          <tbody>
            {state.data.map((item) => (
              <tr key={value(item, 'id')}>
                <td>{value(item, 'export_format')}</td>
                <td>
                  <Link to={`/artifacts/${value(item, 'artifact_id')}`}>
                    {value(item, 'filename')}
                  </Link>
                </td>
                <td>{value(item, 'media_type')}</td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}
