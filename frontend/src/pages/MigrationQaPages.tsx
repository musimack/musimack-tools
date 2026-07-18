import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { migrationQaApi, type MigrationQaPage, type MigrationQaValue } from '../migration-qa/api';
import { downloadArtifact } from '../workflow/api';

const resources = [
  'sources',
  'redirect-map',
  'mappings',
  'redirects',
  'comparisons',
  'findings',
  'recommendations',
  'sitewide',
] as const;
const exportFormats = [
  'findings_csv',
  'redirects_csv',
  'mappings_csv',
  'comparisons_csv',
  'recommendations_csv',
  'sitewide_csv',
  'json',
  'markdown',
] as const;
const terminalStates = new Set(['completed', 'completed_with_warnings', 'failed', 'cancelled']);
const migrationTypes = [
  'domain',
  'protocol',
  'subdomain',
  'cms',
  'platform',
  'url_structure',
  'redesign',
  'consolidation',
  'split',
  'internationalization',
  'other',
] as const;

function value(item: MigrationQaValue | null, key: string): string {
  const raw = item?.[key];
  return typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean'
    ? String(raw)
    : '—';
}
function object(item: MigrationQaValue | null, key: string): MigrationQaValue {
  const raw = item?.[key];
  return typeof raw === 'object' && raw !== null && !Array.isArray(raw)
    ? (raw as MigrationQaValue)
    : {};
}
function readable(raw: string): string {
  return raw.replaceAll('_', ' ');
}
function useLoad<T>(factory: () => Promise<T>, dependencies: readonly unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const factoryRef = useRef(factory);
  // eslint-disable-next-line react-hooks/refs
  factoryRef.current = factory;
  const dependencyKey = JSON.stringify(dependencies);
  const refresh = useCallback(() => {
    setError(null);
    void factoryRef
      .current()
      .then(setData)
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : 'The request failed.');
      });
  }, []);
  useEffect(() => {
    // The asynchronous loader establishes state for the selected resource.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [dependencyKey, refresh]);
  return { data, error, refresh };
}
function Loading({ error }: { error: string | null }) {
  return error ? (
    <ErrorState title="Migration QA unavailable">{error}</ErrorState>
  ) : (
    <Card aria-busy="true">
      <Spinner label="Loading migration QA" />
    </Card>
  );
}
function Tabs({ projectId }: { projectId: string }) {
  return (
    <details className="audit-tabs" open>
      <summary>Migration QA views</summary>
      <nav aria-label="Migration QA views">
        <Link to={`/migration-qa/${projectId}`}>Summary</Link>
        {resources.map((name) => (
          <Link key={name} to={`/migration-qa/${projectId}/${name}`}>
            {readable(name)}
          </Link>
        ))}
        <Link to={`/migration-qa/${projectId}/exports`}>Exports</Link>
      </nav>
    </details>
  );
}

export function MigrationQaProjectsPage() {
  const { can } = useAuth();
  const state = useLoad(() => migrationQaApi.list(), []);
  return (
    <>
      <PageHeader eyebrow="Evidence-backed launch review" title="Website Migration QA">
        Compare operator plans with retained source and destination evidence.
      </PageHeader>
      {can('jobs.submit') ? (
        <Link className="button" to="/migration-qa/new">
          New migration QA project
        </Link>
      ) : (
        <Alert tone="neutral">Viewer access is read-only.</Alert>
      )}
      {!state.data ? (
        <Loading error={state.error} />
      ) : state.data.items.length === 0 ? (
        <EmptyState title="No migration QA projects">
          Create a project from retained crawls.
        </EmptyState>
      ) : (
        <TableFoundation>
          <caption>Migration QA projects</caption>
          <thead>
            <tr>
              <th>Name</th>
              <th>Mode</th>
              <th>State</th>
              <th>Readiness</th>
              <th>Sources</th>
              <th>Findings</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((item) => (
              <tr key={value(item, 'project_id')}>
                <td>
                  <Link to={`/migration-qa/${value(item, 'project_id')}`}>
                    {value(item, 'name')}
                  </Link>
                </td>
                <td>{readable(value(item, 'mode'))}</td>
                <td>
                  <StatusBadge tone="neutral">{readable(value(item, 'state'))}</StatusBadge>
                </td>
                <td>{readable(value(item, 'readiness'))}</td>
                <td>{value(item, 'total_sources')}</td>
                <td>{value(item, 'total_findings')}</td>
              </tr>
            ))}
          </tbody>
        </TableFoundation>
      )}
    </>
  );
}

type Draft = {
  name: string;
  mode: 'pre_launch' | 'post_launch';
  migration_type: (typeof migrationTypes)[number];
  source_run_id: string;
  destination_run_id: string;
  source_origin: string;
  destination_origin: string;
  inventory: string;
  redirects: string;
  preserve_query_parameters: boolean;
  compare_fragments: boolean;
  compare_internal_links: boolean;
  compare_sitemaps: boolean;
  compare_images: boolean;
  compare_structured_data: boolean;
};
const initialDraft: Draft = {
  name: '',
  mode: 'pre_launch',
  migration_type: 'other',
  source_run_id: '',
  destination_run_id: '',
  source_origin: '',
  destination_origin: '',
  inventory: 'source_url,destination_url\n',
  redirects: 'source_url,destination_url,status\n',
  preserve_query_parameters: true,
  compare_fragments: false,
  compare_internal_links: false,
  compare_sitemaps: false,
  compare_images: false,
  compare_structured_data: false,
};
function preview(content: string): { rows: string[][]; errors: string[] } {
  const lines = content.split(/\r?\n/u).filter((line) => line.trim());
  const errors: string[] = [];
  if (new TextEncoder().encode(content).length > 10_000_000) errors.push('Input exceeds 10 MB.');
  const rows = lines.slice(0, 11).map((line) => line.split(/[,\t]/u).map((item) => item.trim()));
  rows.slice(1).forEach((row, index) => {
    if (!row[0]) errors.push(`Row ${String(index + 2)} has no source URL.`);
    if (row.some((item) => item.length > 4096))
      errors.push(`Row ${String(index + 2)} has an overlong field.`);
  });
  return { rows, errors };
}

export function NewMigrationQaPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [draft, setDraft] = useState(initialDraft);
  const [project, setProject] = useState<MigrationQaValue | null>(null);
  const [readiness, setReadiness] = useState<MigrationQaValue | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inventoryPreview = useMemo(() => preview(draft.inventory), [draft.inventory]);
  const redirectPreview = useMemo(() => preview(draft.redirects), [draft.redirects]);
  const set = <K extends keyof Draft>(key: K, next: Draft[K]) => {
    setDraft({ ...draft, [key]: next });
  };
  const prepare = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await migrationQaApi.create({
        name: draft.name,
        mode: draft.mode,
        migration_type: draft.migration_type,
        source_run_id: draft.source_run_id || null,
        destination_run_id: draft.destination_run_id,
        source_origin: draft.source_origin || null,
        destination_origin: draft.destination_origin,
        policy: {
          preserve_query_parameters: draft.preserve_query_parameters,
          compare_fragments: draft.compare_fragments,
          compare_internal_links: draft.compare_internal_links,
          compare_sitemaps: draft.compare_sitemaps,
          compare_images: draft.compare_images,
          compare_structured_data: draft.compare_structured_data,
        },
      });
      const projectId = value(created, 'project_id');
      await migrationQaApi.ingestSources(projectId, draft.inventory);
      if (draft.redirects.trim().split(/\r?\n/u).length > 1)
        await migrationQaApi.ingestRedirects(projectId, draft.redirects);
      setProject(created);
      setReadiness(await migrationQaApi.readiness(projectId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The project could not be prepared.');
    } finally {
      setBusy(false);
    }
  };
  const execute = async () => {
    if (!project) return;
    setBusy(true);
    setError(null);
    const projectId = value(project, 'project_id');
    try {
      await migrationQaApi.execute(projectId);
      for (let attempt = 0; attempt < 20; attempt += 1) {
        const current = await migrationQaApi.detail(projectId);
        if (terminalStates.has(value(current, 'state'))) {
          void navigate(`/migration-qa/${projectId}`);
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
      throw new Error('Migration QA polling exceeded its bounded attempt limit.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Execution failed.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHeader eyebrow="No live-site mutation" title="New migration QA project">
        Preview bounded input, review readiness, then explicitly execute.
      </PageHeader>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <form
        className="workflow-form"
        onSubmit={(event) => {
          event.preventDefault();
          void prepare();
        }}
      >
        <Card>
          <h2>Project and retained runs</h2>
          <label htmlFor="migration-name">Project name</label>
          <input
            id="migration-name"
            required
            maxLength={256}
            value={draft.name}
            onChange={(event) => {
              set('name', event.target.value);
            }}
          />
          <label htmlFor="migration-mode">Mode</label>
          <select
            id="migration-mode"
            value={draft.mode}
            onChange={(event) => {
              set('mode', event.target.value as Draft['mode']);
            }}
          >
            <option value="pre_launch">Pre-launch</option>
            <option value="post_launch">Post-launch</option>
          </select>
          <label htmlFor="migration-type">Migration type</label>
          <select
            id="migration-type"
            value={draft.migration_type}
            onChange={(event) => {
              set('migration_type', event.target.value as Draft['migration_type']);
            }}
          >
            {migrationTypes.map((item) => (
              <option key={item} value={item}>
                {readable(item)}
              </option>
            ))}
          </select>
          <label htmlFor="source-run">Source crawl run ID (optional)</label>
          <input
            id="source-run"
            maxLength={64}
            value={draft.source_run_id}
            onChange={(event) => {
              set('source_run_id', event.target.value);
            }}
          />
          <label htmlFor="destination-run">Destination crawl run ID</label>
          <input
            id="destination-run"
            required
            maxLength={64}
            value={draft.destination_run_id}
            onChange={(event) => {
              set('destination_run_id', event.target.value);
            }}
          />
          <label htmlFor="source-origin">Source origin (optional)</label>
          <input
            id="source-origin"
            type="url"
            value={draft.source_origin}
            onChange={(event) => {
              set('source_origin', event.target.value);
            }}
          />
          <label htmlFor="destination-origin">Destination origin</label>
          <input
            id="destination-origin"
            type="url"
            required
            value={draft.destination_origin}
            onChange={(event) => {
              set('destination_origin', event.target.value);
            }}
          />
        </Card>
        <Card>
          <h2>Policy controls</h2>
          {(
            [
              ['preserve_query_parameters', 'Preserve query parameters'],
              ['compare_fragments', 'Compare fragments'],
              ['compare_internal_links', 'Compare internal links'],
              ['compare_sitemaps', 'Compare sitemaps'],
              ['compare_images', 'Compare images'],
              ['compare_structured_data', 'Compare structured data'],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={draft[key]}
                onChange={(event) => {
                  set(key, event.target.checked);
                }}
              />{' '}
              {label}
            </label>
          ))}
        </Card>
        <InputPreview
          id="source-inventory"
          label="Source inventory CSV, TSV, or URL list"
          value={draft.inventory}
          result={inventoryPreview}
          onChange={(next) => {
            set('inventory', next);
          }}
        />
        <InputPreview
          id="redirect-map"
          label="Redirect map CSV or TSV (optional)"
          value={draft.redirects}
          result={redirectPreview}
          onChange={(next) => {
            set('redirects', next);
          }}
        />
        {!project ? (
          <Button disabled={!can('jobs.submit') || busy || inventoryPreview.errors.length > 0}>
            {busy ? 'Checking…' : 'Create, ingest, and check readiness'}
          </Button>
        ) : null}
      </form>
      {readiness ? (
        <Card>
          <h2>Readiness details</h2>
          <StatusBadge tone={value(readiness, 'readiness') === 'ready' ? 'positive' : 'warning'}>
            {readable(value(readiness, 'readiness'))}
          </StatusBadge>
          <BoundedEvidence value={readiness} />
          <Button
            disabled={
              !can('jobs.submit') ||
              busy ||
              !['ready', 'ready_with_warnings'].includes(value(readiness, 'readiness'))
            }
            onClick={() => void execute()}
          >
            {busy ? 'Executing…' : 'Execute migration QA'}
          </Button>
        </Card>
      ) : null}
    </>
  );
}
function InputPreview({
  id,
  label,
  value: content,
  result,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  result: { rows: string[][]; errors: string[] };
  onChange: (value: string) => void;
}) {
  return (
    <Card>
      <h2>{label}</h2>
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        rows={7}
        required={id === 'source-inventory'}
        value={content}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
      {result.errors.map((item) => (
        <Alert key={item} tone="error">
          {item}
        </Alert>
      ))}
      <details>
        <summary>Parsing preview: {Math.max(0, result.rows.length - 1)} rows shown</summary>
        <div className="table-scroll">
          <TableFoundation>
            <caption>{label} parsing preview</caption>
            <tbody>
              {result.rows.map((row, index) => (
                <tr key={`${String(index)}-${row.join('|')}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${String(cellIndex)}-${cell}`} className="wrap-anywhere">
                      {cell || '—'}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </TableFoundation>
        </div>
      </details>
    </Card>
  );
}

export function MigrationQaDashboardPage() {
  const { projectId = '' } = useParams();
  const state = useLoad(() => migrationQaApi.summary(projectId), [projectId]);
  const counts = object(state.data, 'counts');
  const project = object(state.data, 'project');
  return (
    <>
      <PageHeader eyebrow="Conservative continuity findings" title="Migration QA summary">
        Planned and observed evidence remain separate.
      </PageHeader>
      <Tabs projectId={projectId} />
      {!state.data ? (
        <Loading error={state.error} />
      ) : (
        <>
          <div className="metric-grid">
            <Card>
              <span>State</span>
              <strong>{readable(value(project, 'state'))}</strong>
              <small>{readable(value(project, 'readiness'))}</small>
            </Card>
            {['sources', 'mappings', 'findings', 'recommendations'].map((key) => (
              <Card key={key}>
                <span>{readable(key)}</span>
                <strong>{value(counts, key)}</strong>
              </Card>
            ))}
          </div>
          <Card>
            <h2>Project details</h2>
            <dl className="detail-list">
              <div>
                <dt>Mode</dt>
                <dd>{readable(value(project, 'mode'))}</dd>
              </div>
              <div>
                <dt>Migration type</dt>
                <dd>{readable(value(project, 'migration_type'))}</dd>
              </div>
              <div>
                <dt>Source origin</dt>
                <dd className="wrap-anywhere">{value(project, 'source_origin')}</dd>
              </div>
              <div>
                <dt>Destination origin</dt>
                <dd className="wrap-anywhere">{value(project, 'destination_origin')}</dd>
              </div>
            </dl>
          </Card>
        </>
      )}
    </>
  );
}

export function MigrationQaInventoryPage() {
  const { projectId = '', resource = 'findings' } = useParams();
  const [params, setParams] = useSearchParams();
  const previousResource = useRef(resource);
  const filters = {
    page_size: 25,
    cursor: params.get('cursor'),
    search: params.get('search'),
    source_search: params.get('source'),
    destination_search: params.get('destination'),
    code: params.get('code'),
    category: params.get('category'),
    severity: params.get('severity'),
    confidence: params.get('confidence'),
    human_review: params.get('review'),
    state: params.get('state'),
  };
  const state = useLoad(
    () => migrationQaApi.resource(projectId, resource, filters),
    [projectId, resource, ...Object.values(filters)],
  );
  const update = (key: string, next: string) => {
    const copy = new URLSearchParams(params);
    if (next) copy.set(key, next);
    else copy.delete(key);
    if (key !== 'cursor') copy.delete('cursor');
    setParams(copy);
  };
  useEffect(() => {
    if (previousResource.current !== resource) {
      previousResource.current = resource;
      setParams(new URLSearchParams());
    }
  }, [resource, setParams]);
  return (
    <>
      <PageHeader eyebrow="Bounded retained evidence" title={readable(resource)}>
        Use server-bound filters and cursor pagination.
      </PageHeader>
      <Tabs projectId={projectId} />
      <FilterBar
        params={params}
        update={update}
        reset={() => {
          setParams(new URLSearchParams());
        }}
      />
      {!state.data ? (
        <Loading error={state.error} />
      ) : (
        <ResourceTable resource={resource} page={state.data} />
      )}
      {state.data ? (
        <div className="toolbar">
          <Button
            disabled={!params.get('cursor')}
            onClick={() => {
              update('cursor', '');
            }}
          >
            First page
          </Button>
          <span>
            {state.data.items.length} of {state.data.total}
          </span>
          <Button
            disabled={!state.data.next_cursor}
            onClick={() => {
              update('cursor', state.data?.next_cursor ?? '');
            }}
          >
            Next
          </Button>
        </div>
      ) : null}
    </>
  );
}
function FilterBar({
  params,
  update,
  reset,
}: {
  params: URLSearchParams;
  update: (key: string, value: string) => void;
  reset: () => void;
}) {
  return (
    <form
      className="filter-bar"
      onSubmit={(event) => {
        event.preventDefault();
      }}
    >
      <label>
        URL search
        <input
          value={params.get('search') ?? ''}
          onChange={(event) => {
            update('search', event.target.value);
          }}
        />
      </label>
      <label>
        Source search
        <input
          value={params.get('source') ?? ''}
          onChange={(event) => {
            update('source', event.target.value);
          }}
        />
      </label>
      <label>
        Destination search
        <input
          value={params.get('destination') ?? ''}
          onChange={(event) => {
            update('destination', event.target.value);
          }}
        />
      </label>
      <label>
        Finding code
        <input
          value={params.get('code') ?? ''}
          onChange={(event) => {
            update('code', event.target.value);
          }}
        />
      </label>
      <label>
        Category
        <input
          value={params.get('category') ?? ''}
          onChange={(event) => {
            update('category', event.target.value);
          }}
        />
      </label>
      <label>
        Severity
        <select
          value={params.get('severity') ?? ''}
          onChange={(event) => {
            update('severity', event.target.value);
          }}
        >
          <option value="">All</option>
          <option value="error">Error</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </select>
      </label>
      <label>
        Confidence
        <select
          value={params.get('confidence') ?? ''}
          onChange={(event) => {
            update('confidence', event.target.value);
          }}
        >
          <option value="">All</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
          <option value="indeterminate">Indeterminate</option>
        </select>
      </label>
      <label>
        Human review
        <select
          value={params.get('review') ?? ''}
          onChange={(event) => {
            update('review', event.target.value);
          }}
        >
          <option value="">All</option>
          <option value="true">Required</option>
          <option value="false">Not required</option>
        </select>
      </label>
      <label>
        State
        <input
          value={params.get('state') ?? ''}
          onChange={(event) => {
            update('state', event.target.value);
          }}
        />
      </label>
      <Button type="button" onClick={reset}>
        Reset filters
      </Button>
    </form>
  );
}
function ResourceTable({ resource, page }: { resource: string; page: MigrationQaPage }) {
  if (!page.items.length)
    return <EmptyState title="No matching rows">Reset filters or inspect another view.</EmptyState>;
  return (
    <div className="table-scroll">
      <TableFoundation>
        <caption>
          {readable(resource)} — {page.total} rows
        </caption>
        <thead>
          <tr>
            <th>Code, action, or state</th>
            <th>Source</th>
            <th>Destination</th>
            <th>Severity</th>
            <th>Confidence</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {page.items.map((item, index) => (
            <tr
              key={
                value(item, 'stable_id') === '—'
                  ? value(item, 'id') === '—'
                    ? index
                    : value(item, 'id')
                  : value(item, 'stable_id')
              }
            >
              <td>
                {value(item, 'code') !== '—'
                  ? readable(value(item, 'code'))
                  : value(item, 'action') !== '—'
                    ? readable(value(item, 'action'))
                    : readable(value(item, 'state'))}
              </td>
              <td className="wrap-anywhere">
                {value(item, 'source_url') !== '—'
                  ? value(item, 'source_url')
                  : value(item, 'raw_url')}
              </td>
              <td className="wrap-anywhere">
                {value(item, 'destination_url') !== '—'
                  ? value(item, 'destination_url')
                  : value(item, 'normalized_destination_url')}
              </td>
              <td>{value(item, 'severity')}</td>
              <td>{value(item, 'confidence')}</td>
              <td>
                <BoundedEvidence value={item} />
              </td>
            </tr>
          ))}
        </tbody>
      </TableFoundation>
    </div>
  );
}
function BoundedEvidence({ value: item }: { value: MigrationQaValue }) {
  const text = JSON.stringify(item, null, 2);
  return (
    <details>
      <summary>Bounded evidence</summary>
      <pre className="wrap-anywhere">{text.length > 4096 ? `${text.slice(0, 4096)}…` : text}</pre>
    </details>
  );
}

export function MigrationQaExportsPage() {
  const { projectId = '' } = useParams();
  const { can } = useAuth();
  const state = useLoad(() => migrationQaApi.exports(projectId), [projectId]);
  const [message, setMessage] = useState('');
  const create = (format: string) => {
    setMessage('');
    void migrationQaApi
      .export(projectId, format)
      .then(() => {
        setMessage(`${readable(format)} created`);
        state.refresh();
      })
      .catch((reason: unknown) => {
        setMessage(reason instanceof Error ? reason.message : 'Export failed.');
      });
  };
  return (
    <>
      <PageHeader eyebrow="Stored local artifacts" title="Migration QA exports">
        Generate and retrieve eight authenticated artifacts.
      </PageHeader>
      <Tabs projectId={projectId} />
      <Card>
        <div className="export-actions">
          {exportFormats.map((format) => (
            <Button
              key={format}
              disabled={!can('jobs.submit')}
              onClick={() => {
                create(format);
              }}
            >
              {readable(format)}
            </Button>
          ))}
        </div>
        {message ? (
          <Alert tone={message.includes('created') ? 'neutral' : 'error'}>{message}</Alert>
        ) : null}
      </Card>
      <Card>
        <h2>Artifact history</h2>
        {!state.data ? (
          <Loading error={state.error} />
        ) : state.data.length === 0 ? (
          <EmptyState title="No exports">Generate an export above.</EmptyState>
        ) : (
          <TableFoundation>
            <caption>Migration QA artifact history</caption>
            <thead>
              <tr>
                <th>Format</th>
                <th>Filename</th>
                <th>Rows</th>
                <th>State</th>
                <th>Download</th>
              </tr>
            </thead>
            <tbody>
              {state.data.map((item) => (
                <tr
                  key={
                    value(item, 'stable_id') === '—' ? value(item, 'id') : value(item, 'stable_id')
                  }
                >
                  <td>{readable(value(item, 'export_format'))}</td>
                  <td className="wrap-anywhere">
                    <Link to={`/artifacts/${value(item, 'artifact_id')}`}>
                      {value(item, 'filename')}
                    </Link>
                  </td>
                  <td>{value(item, 'row_count')}</td>
                  <td>{readable(value(item, 'state'))}</td>
                  <td>
                    <Button
                      disabled={!can('artifacts.download')}
                      onClick={() =>
                        void downloadArtifact(
                          value(item, 'artifact_id'),
                          value(item, 'filename'),
                        ).catch(() => {
                          setMessage('Artifact is missing, corrupt, or unavailable.');
                        })
                      }
                    >
                      Download
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </TableFoundation>
        )}
      </Card>
    </>
  );
}
