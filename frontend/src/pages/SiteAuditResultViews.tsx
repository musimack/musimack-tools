import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Spinner,
  StatusBadge,
  TableFoundation,
} from '../design-system/components';
import { artifactDownloadUrl, siteAuditsApi } from '../site-audits/api';
import type { AuditPage } from '../site-audits/contracts';

type Row = Record<string, unknown>;

const text = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return 'Not available';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.length ? value.map(text).join(', ') : 'None';
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).slice(0, 30);
    return entries.length
      ? entries.map(([key, item]) => `${key.replaceAll('_', ' ')}: ${text(item)}`).join(' · ')
      : 'None';
  }
  if (typeof value === 'string') return value.replaceAll('_', ' ');
  if (typeof value === 'number' || typeof value === 'bigint') return value.toString();
  return 'Not available';
};

const date = (value: unknown): string => {
  if (typeof value !== 'string' || !value) return 'Not available';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString();
};

const errorMessage = (error: unknown): string =>
  error instanceof ApiError
    ? `${error.message}${error.requestId ? ` Support reference: ${error.requestId}.` : ''}`
    : error instanceof Error
      ? error.message
      : 'The result could not be loaded.';

const rows = (value: unknown): Row[] => (Array.isArray(value) ? (value as Row[]) : []);
const row = (value: unknown): Row =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Row) : {};

function Loading() {
  return (
    <Card aria-busy="true">
      <Spinner label="Loading retained result" /> Loading retained result…
    </Card>
  );
}

function Failure({ error }: { error: string }) {
  return <ErrorState title="Result unavailable">{error}</ErrorState>;
}

function FieldGrid({ values }: { values: [string, unknown][] }) {
  return (
    <dl className="result-fields">
      {values.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className="wrap-anywhere">{text(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function ResultCount({ page }: { page: AuditPage<unknown> }) {
  if (!page.total) return <p role="status">No retained records match these filters.</p>;
  return (
    <p role="status">
      {page.offset + 1}–{Math.min(page.offset + page.items.length, page.total)} of{' '}
      {page.total.toLocaleString()}
    </p>
  );
}

function Pager({
  page,
  onOffset,
}: {
  page: AuditPage<unknown>;
  onOffset: (value: number) => void;
}) {
  return (
    <nav className="pagination" aria-label="Result pagination">
      <Button
        type="button"
        disabled={page.offset === 0}
        onClick={() => {
          onOffset(Math.max(0, page.offset - page.page_size));
        }}
      >
        Previous
      </Button>
      <ResultCount page={page} />
      <Button
        type="button"
        disabled={page.offset + page.page_size >= page.total}
        onClick={() => {
          onOffset(page.offset + page.page_size);
        }}
      >
        Next
      </Button>
    </nav>
  );
}

function useRouteFilters() {
  const [parameters, setParameters] = useSearchParams();
  const offset = Math.max(0, Number(parameters.get('offset') ?? 0) || 0);
  const set = (key: string, value: string | boolean | number | null, reset = true) => {
    const next = new URLSearchParams(parameters);
    if (value === null || value === '' || value === false) next.delete(key);
    else next.set(key, String(value));
    if (reset && key !== 'offset') next.set('offset', '0');
    setParameters(next);
  };
  return {
    parameters,
    offset,
    set,
    reset: () => {
      setParameters(new URLSearchParams());
    },
  };
}

function FilterInput({
  label,
  name,
  parameters,
  set,
}: {
  label: string;
  name: string;
  parameters: URLSearchParams;
  set: (key: string, value: string) => void;
}) {
  return (
    <label>
      {label}
      <input
        value={parameters.get(name) ?? ''}
        onChange={(event) => {
          set(name, event.target.value);
        }}
      />
    </label>
  );
}

function FilterSelect({
  label,
  name,
  options,
  parameters,
  set,
}: {
  label: string;
  name: string;
  options: string[];
  parameters: URLSearchParams;
  set: (key: string, value: string) => void;
}) {
  return (
    <label>
      {label}
      <select
        value={parameters.get(name) ?? ''}
        onChange={(event) => {
          set(name, event.target.value);
        }}
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {text(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

export function SitemapResult({ auditId }: { auditId: string }) {
  const { parameters, offset, set, reset } = useRouteFilters();
  const [comparison, setComparison] = useState<AuditPage<Row> & Row>();
  const [documents, setDocuments] = useState<AuditPage<Row>>();
  const [error, setError] = useState<string>();
  const url = parameters.get('url') ?? '';
  const state = parameters.get('state') ?? '';
  const partial = parameters.get('partial') === 'true';
  const documentType = parameters.get('document_type') ?? '';
  const parseState = parameters.get('parse_state') ?? '';
  useEffect(() => {
    let live = true;
    Promise.all([
      siteAuditsApi.projection(auditId, 'sitemap-comparisons', offset, 50, {
        url,
        state,
        partial,
      }),
      siteAuditsApi.projection(auditId, 'sitemap-documents', 0, 50, {
        url,
        document_type: documentType,
        parse_state: parseState,
        partial,
      }),
    ]).then(
      ([comparisonValue, documentValue]) => {
        if (live) {
          setComparison(comparisonValue as AuditPage<Row> & Row);
          setDocuments(documentValue as AuditPage<Row>);
        }
      },
      (caught: unknown) => {
        if (live) setError(errorMessage(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [auditId, documentType, offset, parseState, partial, state, url]);
  if (error) return <Failure error={error} />;
  if (!comparison || !documents) return <Loading />;
  const module = row(comparison.existing_sitemap_module);
  const totals = row(comparison.comparison_totals);
  return (
    <div className="result-stack">
      <Card>
        <h2>Sitemap</h2>
        <p>Existing Sitemap Audit evidence remains distinct from generated recommendations.</p>
        <FieldGrid
          values={[
            ['Module state', module.lifecycle],
            ['Completeness', module.completeness],
            ['Execution source', module.execution_source],
            ['Specialist provenance', module.specialist_audit_id],
            ['Document count', comparison.document_count],
            [
              'Index count',
              documents.items.filter((item) => item.root_type === 'sitemap_index').length,
            ],
            [
              'Entry count',
              documents.items.reduce((sum, item) => sum + Number(item.entry_count ?? 0), 0),
            ],
            [
              'Invalid documents',
              documents.items.filter((item) => item.parse_state !== 'parsed').length,
            ],
            [
              'Sitemap-only URLs',
              comparison.items.filter((item) => item.discovery_state === 'sitemap_only').length,
            ],
            ['Recommended artifact', 'See Artifacts → Recommended sitemap XML'],
            [
              'Include / Exclude / Review / Indeterminate',
              `${text(totals.include)} / ${text(totals.exclude)} / ${text(totals.review)} / ${text(totals.indeterminate)}`,
            ],
          ]}
        />
        <Alert tone="neutral">
          No live publication action is available from this review screen.
        </Alert>
      </Card>
      <Card>
        <h3>Filter sitemap evidence</h3>
        <div className="filter-bar">
          <FilterInput label="URL contains" name="url" parameters={parameters} set={set} />
          <FilterSelect
            label="Document type"
            name="document_type"
            options={['urlset', 'sitemap_index']}
            parameters={parameters}
            set={set}
          />
          <FilterSelect
            label="Parse state"
            name="parse_state"
            options={['parsed', 'invalid', 'failed']}
            parameters={parameters}
            set={set}
          />
          <FilterSelect
            label="Recommendation"
            name="state"
            options={['include', 'exclude', 'review', 'indeterminate']}
            parameters={parameters}
            set={set}
          />
          <label>
            <input
              type="checkbox"
              checked={partial}
              onChange={(event) => {
                set('partial', event.target.checked);
              }}
            />{' '}
            Partial only
          </label>
          <Button type="button" onClick={reset}>
            Clear filters
          </Button>
        </div>
      </Card>
      <Card>
        <h3>Existing sitemap documents</h3>
        {documents.items.length ? (
          <TableFoundation>
            <thead>
              <tr>
                <th scope="col">Sitemap URL</th>
                <th scope="col">Type / parent</th>
                <th scope="col">Fetch</th>
                <th scope="col">Parse</th>
                <th scope="col">Counts</th>
                <th scope="col">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {documents.items.map((item) => (
                <tr key={text(item.document_id)}>
                  <td className="wrap-anywhere">{text(item.requested_url)}</td>
                  <td>
                    {text(item.root_type)}
                    <small>Parent: {text(item.parent_document_id)}</small>
                  </td>
                  <td>
                    {text(item.fetch_state)}
                    <small>HTTP {text(item.http_status)}</small>
                  </td>
                  <td>{text(item.parse_state)}</td>
                  <td>
                    {text(item.entry_count)} entries
                    <small>
                      {text(item.child_count)} children · {text(item.validation_count)} invalid
                    </small>
                  </td>
                  <td className="technical-id">{text(item.document_id)}</td>
                </tr>
              ))}
            </tbody>
          </TableFoundation>
        ) : (
          <EmptyState title="No matching sitemap documents">
            The linked specialist retained no documents for these filters.
          </EmptyState>
        )}
      </Card>
      <Card>
        <h3>Existing versus recommended</h3>
        {comparison.items.length ? (
          <TableFoundation>
            <thead>
              <tr>
                <th scope="col">URL</th>
                <th scope="col">Existing</th>
                <th scope="col">Recommended</th>
                <th scope="col">Comparison</th>
                <th scope="col">Reason</th>
                <th scope="col">Fetch evidence</th>
                <th scope="col">Governance</th>
              </tr>
            </thead>
            <tbody>
              {comparison.items.map((item) => (
                <tr key={text(item.url_id)}>
                  <td>
                    <Link
                      to={`/site-audits/${auditId}/results/pages/${text(item.sequence)}?return=${encodeURIComponent(parameters.toString())}`}
                    >
                      {text(item.url)}
                    </Link>
                  </td>
                  <td>{text(item.existing_sitemap_state)}</td>
                  <td>{text(item.recommended_sitemap_state)}</td>
                  <td>{text(item.comparison_state)}</td>
                  <td>{text(item.primary_reason)}</td>
                  <td>
                    HTTP {text(item.http_status)}
                    <small>
                      {text(item.indexability_state)} · {text(item.canonical_state)}
                    </small>
                  </td>
                  <td>
                    {text(item.robots_state)}
                    <small>{item.partial ? 'Partial evidence' : 'Complete evidence'}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </TableFoundation>
        ) : (
          <EmptyState title="No matching comparisons">
            No URL comparison matches these filters.
          </EmptyState>
        )}
        <Pager
          page={comparison}
          onOffset={(value) => {
            set('offset', value, false);
          }}
        />
      </Card>
    </div>
  );
}

export function ExclusionsResult({ auditId }: { auditId: string }) {
  const { parameters, offset, set, reset } = useRouteFilters();
  const [page, setPage] = useState<AuditPage<Row>>();
  const [error, setError] = useState<string>();
  const filter = (name: string) => parameters.get(name) ?? '';
  const url = filter('url');
  const decisionLayer = filter('decision_layer');
  const action = filter('action');
  const reason = filter('reason');
  const enqueued = filter('enqueued');
  const fetched = filter('fetched');
  const override = parameters.get('override') === 'true';
  const conflict = parameters.get('conflict') === 'true';
  const partial = parameters.get('partial') === 'true';
  useEffect(() => {
    let live = true;
    void siteAuditsApi
      .projection(auditId, 'exclusions', offset, 50, {
        url,
        decision_layer: decisionLayer,
        action,
        reason,
        enqueued,
        fetched,
        override,
        conflict,
        partial,
      })
      .then(
        (value) => {
          if (live) setPage(value as AuditPage<Row>);
        },
        (caught: unknown) => {
          if (live) setError(errorMessage(caught));
        },
      );
    return () => {
      live = false;
    };
  }, [
    action,
    auditId,
    conflict,
    decisionLayer,
    enqueued,
    fetched,
    offset,
    override,
    partial,
    reason,
    url,
  ]);
  if (error) return <Failure error={error} />;
  if (!page) return <Loading />;
  return (
    <Card>
      <h2>URL governance decisions</h2>
      <p>
        Discovery, metadata scoring, sitemap policy, review, and normalization outcomes remain
        distinct.
      </p>
      <div className="filter-bar">
        <FilterInput label="URL contains" name="url" parameters={parameters} set={set} />
        <FilterSelect
          label="Decision layer"
          name="decision_layer"
          options={['discovery', 'metadata_scoring', 'sitemap']}
          parameters={parameters}
          set={set}
        />
        <FilterSelect
          label="Action"
          name="action"
          options={[
            'exclude_from_discovery',
            'exclude_from_metadata_scoring',
            'exclude_from_sitemap',
            'review',
            'strip_tracking_parameters',
          ]}
          parameters={parameters}
          set={set}
        />
        <FilterInput label="Reason contains" name="reason" parameters={parameters} set={set} />
        <FilterSelect
          label="Enqueued"
          name="enqueued"
          options={['enqueued', 'not_enqueued']}
          parameters={parameters}
          set={set}
        />
        <FilterSelect
          label="Fetched"
          name="fetched"
          options={['fetched', 'not_fetched', 'failed']}
          parameters={parameters}
          set={set}
        />
        <label>
          <input
            type="checkbox"
            checked={override}
            onChange={(event) => {
              set('override', event.target.checked);
            }}
          />{' '}
          Overrides only
        </label>
        <label>
          <input
            type="checkbox"
            checked={conflict}
            onChange={(event) => {
              set('conflict', event.target.checked);
            }}
          />{' '}
          Conflicts only
        </label>
        <label>
          <input
            type="checkbox"
            checked={partial}
            onChange={(event) => {
              set('partial', event.target.checked);
            }}
          />{' '}
          Partial only
        </label>
        <Button type="button" onClick={reset}>
          Clear filters
        </Button>
      </div>
      {page.items.length ? (
        <TableFoundation>
          <thead>
            <tr>
              <th scope="col">Original / normalized URL</th>
              <th scope="col">Layer and action</th>
              <th scope="col">Primary rule</th>
              <th scope="col">Reason</th>
              <th scope="col">Lifecycle</th>
              <th scope="col">State</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((item) => {
              const matches = rows(item.rule_matches);
              const primary = matches.find((match) => match.primary_rule) ?? matches[0] ?? {};
              const primaryRule = row(primary.rule);
              return (
                <tr key={text(item.url_id)}>
                  <td className="wrap-anywhere">
                    {text(item.original_url)}
                    <small>{text(item.normalized_url)}</small>
                  </td>
                  <td>
                    {text(primary.decision_layer)}
                    <small>
                      {text(item.discovery_decision)} · {text(item.metadata_scoring_decision)} ·{' '}
                      {text(item.sitemap_policy_decision)}
                    </small>
                  </td>
                  <td>
                    {text(primaryRule.stable_rule_id ?? primary.snapshot_rule_id)}
                    <small>
                      {text(primaryRule.rule_source)} · {text(primaryRule.source_version)} ·{' '}
                      {matches.length} contributing rule(s)
                    </small>
                    <small>
                      {text(primaryRule.match_type)}: {text(primaryRule.match_value)} · specificity{' '}
                      {text(primaryRule.specificity)} · priority {text(primaryRule.priority)}
                    </small>
                  </td>
                  <td className="wrap-anywhere">{text(primary.reason ?? item.failure_code)}</td>
                  <td>
                    {text(item.enqueued_state)}
                    <small>
                      {text(item.fetch_state)} · {date(item.updated_at)}
                    </small>
                  </td>
                  <td>
                    {primary.overridden ? 'Overridden' : 'Effective'}
                    <small>
                      {primary.conflict_code
                        ? `Conflict: ${text(primary.conflict_code)}`
                        : item.partial
                          ? 'Partial evidence'
                          : 'No conflict'}
                    </small>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </TableFoundation>
      ) : (
        <EmptyState title="No matching governance decisions">
          No governed URL matches these filters.
        </EmptyState>
      )}
      <Pager
        page={page}
        onOffset={(value) => {
          set('offset', value, false);
        }}
      />
    </Card>
  );
}

export function EvidenceResult({ auditId }: { auditId: string }) {
  const { parameters, offset, set, reset } = useRouteFilters();
  const [value, setValue] = useState<Row>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let live = true;
    void siteAuditsApi.projection(auditId, 'evidence').then(
      (result) => {
        if (live) setValue(row(result));
      },
      (caught: unknown) => {
        if (live) setError(errorMessage(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [auditId]);
  if (error) return <Failure error={error} />;
  if (!value) return <Loading />;
  const type = parameters.get('type') ?? '';
  const severity = parameters.get('severity') ?? '';
  const url = parameters.get('url') ?? '';
  const partial = parameters.get('partial') === 'true';
  const findings = rows(value.findings).filter(
    (item) =>
      (!type || item.module === type) &&
      (!severity || item.severity === severity) &&
      (!url || text(item.url).toLowerCase().includes(url.toLowerCase())) &&
      (!partial || item.determinacy === 'indeterminate'),
  );
  const page: AuditPage<Row> = {
    items: findings.slice(offset, offset + 50),
    offset,
    page_size: 50,
    total: findings.length,
    ordering: 'code,finding_id',
  };
  return (
    <div className="result-stack">
      <Card>
        <h2>Evidence</h2>
        <p>
          Structured retained evidence only. Raw HTML, response bodies, arbitrary headers, secrets,
          local paths, database errors, and stack traces are not retained here.
        </p>
        <nav className="section-nav" aria-label="Evidence sections">
          <a href="#crawl">Crawl</a>
          <a href="#modules">Modules</a>
          <a href="#findings">Warnings and findings</a>
          <a href="#provenance">Provenance</a>
        </nav>
      </Card>
      <Card id="crawl">
        <h3>Crawl and orchestration evidence</h3>
        <FieldGrid
          values={[
            ['Lifecycle', row(value.audit).lifecycle],
            ['Current stage', row(value.orchestration).current_stage],
            ['Crawl job', row(value.orchestration).crawl_job_id],
            ['Crawl run', row(value.orchestration).crawl_run_id],
            ['Response bodies retained', value.body_content_retained],
            ['Projection version', value.projection_version],
          ]}
        />
        <details>
          <summary>Stage evidence</summary>
          <StructuredRows values={rows(value.stages)} />
        </details>
      </Card>
      <Card id="modules">
        <h3>Module completeness</h3>
        <StructuredRows values={rows(value.modules)} />
        <h4>Specialist provenance</h4>
        <StructuredRows values={rows(value.specialists)} />
      </Card>
      <Card id="findings">
        <h3>Warnings, failures, and page evidence</h3>
        <div className="filter-bar">
          <FilterSelect
            label="Evidence type"
            name="type"
            options={[
              'crawl',
              'metadata',
              'sitemap',
              'links',
              'internal_links',
              'images',
              'structured_data',
            ]}
            parameters={parameters}
            set={set}
          />
          <FilterSelect
            label="Severity"
            name="severity"
            options={['critical', 'high', 'medium', 'low', 'warning', 'informational']}
            parameters={parameters}
            set={set}
          />
          <FilterInput label="URL contains" name="url" parameters={parameters} set={set} />
          <label>
            <input
              type="checkbox"
              checked={partial}
              onChange={(event) => {
                set('partial', event.target.checked);
              }}
            />{' '}
            Partial only
          </label>
          <Button type="button" onClick={reset}>
            Clear filters
          </Button>
        </div>
        {page.items.length ? (
          <TableFoundation>
            <thead>
              <tr>
                <th scope="col">Type</th>
                <th scope="col">Code</th>
                <th scope="col">Severity</th>
                <th scope="col">Explanation</th>
                <th scope="col">Determinacy</th>
                <th scope="col">Evidence ID</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((item) => (
                <tr key={text(item.finding_id)}>
                  <td>{text(item.module)}</td>
                  <td>{text(item.code)}</td>
                  <td>{text(item.severity)}</td>
                  <td className="wrap-anywhere">{text(item.explanation)}</td>
                  <td>
                    {text(item.determinacy)}
                    <small>{text(item.confidence)} confidence</small>
                  </td>
                  <td className="technical-id">{text(item.evidence_reference)}</td>
                </tr>
              ))}
            </tbody>
          </TableFoundation>
        ) : (
          <EmptyState title="No matching evidence">
            No retained finding matches these filters.
          </EmptyState>
        )}
        <Pager
          page={page}
          onOffset={(next) => {
            set('offset', next, false);
          }}
        />
      </Card>
      <Card id="provenance">
        <h3>Evidence coverage</h3>
        <p>
          Crawl, discovery, redirect, robots, indexability, canonical, metadata, links, images,
          structured data, sitemap, module completeness, specialist provenance, and projection
          versions are presented when retained by their owning module.
        </p>
      </Card>
    </div>
  );
}

function StructuredRows({ values }: { values: Row[] }) {
  if (!values.length) return <p>No retained records are available.</p>;
  return (
    <div className="structured-list">
      {values.map((item, index) => (
        <details key={text(item.id ?? item.module ?? item.stage ?? index)}>
          <summary>
            {text(item.module ?? item.stage ?? item.code ?? `Record ${String(index + 1)}`)}
          </summary>
          <FieldGrid
            values={Object.entries(item).filter(
              ([key]) => !/body|raw_html|secret|token|password|filesystem|path_on_disk/iu.test(key),
            )}
          />
        </details>
      ))}
    </div>
  );
}

export function SettingsSnapshotResult({ auditId }: { auditId: string }) {
  const [value, setValue] = useState<Row>();
  const [error, setError] = useState<string>();
  const { offset, set } = useRouteFilters();
  useEffect(() => {
    let live = true;
    void siteAuditsApi.projection(auditId, 'snapshot').then(
      (result) => {
        if (live) setValue(row(result));
      },
      (caught: unknown) => {
        if (live) setError(errorMessage(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [auditId]);
  if (error) return <Failure error={error} />;
  if (!value) return <Loading />;
  const configuration = row(value.configuration);
  const rules = rows(value.rules ?? configuration.rules);
  const page: AuditPage<Row> = {
    items: rules.slice(offset, offset + 50),
    offset,
    page_size: 50,
    total: rules.length,
    ordering: 'snapshot order',
  };
  return (
    <div className="result-stack">
      <Alert tone="neutral">
        This submitted settings snapshot is immutable. It has no edit controls.
      </Alert>
      <Card>
        <h2>Settings Snapshot</h2>
        <FieldGrid
          values={[
            ['Audit identity', value.audit_id],
            ['Snapshot identity', value.snapshot_id],
            ['Snapshot timestamp', date(value.created_at)],
            ['Integrity SHA-256', value.sha256],
            ['Application version', value.application_version],
            ['Projection version', value.projection_version],
            ['Population definition', value.population_definition_version],
            ['Priority model', value.priority_model_version],
          ]}
        />
      </Card>
      <Card>
        <h3>Scope and crawl</h3>
        <FieldGrid
          values={[
            ['Approved hosts', value.approved_hosts_json ?? configuration.approved_hosts],
            ['Scope policy', value.scope_policy_json ?? configuration.scope_policy],
            ['Crawl limits', value.crawl_limits_json ?? configuration.crawl_limits],
            ['Thresholds', value.thresholds_json ?? configuration.thresholds],
            ['Enabled modules', value.enabled_modules_json ?? configuration.enabled_modules],
          ]}
        />
      </Card>
      <Card>
        <h3>Preset, profile, and accepted governance</h3>
        <FieldGrid
          values={[
            ['Platform preset', value.platform_preset_id],
            ['Platform preset version', value.platform_preset_version],
            ['Site profile', value.site_profile_id],
            ['Site profile version', value.site_profile_version],
            ['Preset accepted', configuration.preset_accepted],
            ['Tracking parameters accepted', configuration.tracking_parameters_accepted],
            [
              'Tracking parameters',
              value.tracking_parameters_json ?? configuration.tracking_parameters,
            ],
            [
              'Disabled inherited rules',
              value.disabled_rules ?? configuration.disabled_inherited_rules,
            ],
            ['Per-audit overrides', configuration.overrides],
            [
              'Artifact schema versions',
              value.artifact_schema_versions_json ?? configuration.artifact_schema_versions,
            ],
          ]}
        />
      </Card>
      <Card>
        <h3>Effective rules</h3>
        {page.items.length ? (
          <StructuredRows values={page.items} />
        ) : (
          <EmptyState title="No effective rules">
            No effective URL-governance rules were snapshotted.
          </EmptyState>
        )}
        <Pager
          page={page}
          onOffset={(next) => {
            set('offset', next, false);
          }}
        />
      </Card>
    </div>
  );
}

const artifactPurpose: Record<string, string> = {
  executive_markdown: 'Executive Markdown',
  page_inventory_csv: 'Page inventory CSV',
  full_evidence_json: 'Evidence JSON',
  grouped_issues_csv: 'Grouped issues CSV',
  sitemap_comparison_csv: 'Sitemap comparison CSV',
  excluded_urls_csv: 'Excluded URLs CSV',
  applied_rules_csv: 'Applied rules CSV',
  recommended_sitemap_xml: 'Recommended sitemap XML',
  action_plan_csv: 'Action plan CSV',
  configuration_snapshot_json: 'Configuration snapshot JSON',
};

export function ArtifactsResult({ auditId }: { auditId: string }) {
  const [items, setItems] = useState<Row[]>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let live = true;
    void siteAuditsApi.projection(auditId, 'artifacts').then(
      (value) => {
        if (live) setItems(rows(value));
      },
      (caught: unknown) => {
        if (live) setError(errorMessage(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [auditId]);
  if (error) return <Failure error={error} />;
  if (!items) return <Loading />;
  return (
    <Card>
      <h2>Artifacts</h2>
      <p>
        Authenticated retained exports. No local filesystem paths or live XML publication controls
        are shown.
      </p>
      {items.length ? (
        <div className="artifact-grid">
          {items.map((association) => {
            const artifact = row(association.artifact);
            const available = artifact.download_available === true;
            const purpose =
              typeof association.purpose === 'string' ? association.purpose : 'unknown_artifact';
            const purposeLabel = artifactPurpose[purpose] ?? text(purpose);
            return (
              <article className="artifact-card" key={text(association.id)}>
                <div className="card-heading">
                  <h3>{purposeLabel}</h3>
                  <StatusBadge tone={available ? 'positive' : 'neutral'}>
                    {text(artifact.lifecycle_state ?? 'unavailable')}
                  </StatusBadge>
                </div>
                <FieldGrid
                  values={[
                    ['Filename', artifact.filename],
                    ['MIME type', artifact.content_type],
                    [
                      'Size',
                      typeof artifact.byte_count === 'number'
                        ? `${artifact.byte_count.toLocaleString()} bytes`
                        : artifact.byte_count,
                    ],
                    ['SHA-256', artifact.sha256],
                    ['Schema version', association.schema_version],
                    ['Created', date(artifact.created_at ?? association.created_at)],
                    ['Completeness', association.completeness],
                    ['Partial data', association.truncated],
                    ['Lifecycle', artifact.lifecycle_state],
                    ['Version', 'Current retained association'],
                  ]}
                />
                {available ? (
                  <a className="button" href={artifactDownloadUrl(text(association.artifact_id))}>
                    Download {purposeLabel}
                  </a>
                ) : (
                  <Button disabled>Download unavailable</Button>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState title="No retained artifacts">
          Artifacts are unavailable or still generating for this audit.
        </EmptyState>
      )}
    </Card>
  );
}
