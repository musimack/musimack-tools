import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ApiError } from '../api/client';
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
import { siteAuditSettingsApi } from '../site-audit-settings/api';
import type { Preset, SiteProfile } from '../site-audit-settings/contracts';
import { safeHttpUrl, siteAuditsApi } from '../site-audits/api';
import {
  ArtifactsResult,
  EvidenceResult,
  ExclusionsResult,
  SettingsSnapshotResult,
  SitemapResult,
} from './SiteAuditResultViews';
import {
  defaultDraft,
  editableStates,
  lifecycleStates,
  terminalStates,
  type AuditDetail,
  type AuditPage,
  type AuditRecord,
  type IssueFilters,
  type IssueRecord,
  type PageFilters,
  type SiteAuditDraft,
  type UrlRecord,
} from '../site-audits/contracts';

const steps = [
  'Website',
  'Platform and Preset',
  'URL Governance',
  'Crawl Limits',
  'Audit Modules',
  'Thresholds',
  'Review and Submit',
] as const;

const modules = [
  ['metadata', 'Metadata'],
  ['sitemap', 'Sitemap'],
  ['links', 'Links'],
  ['internal_links', 'Internal links'],
  ['images', 'Images and alt text'],
  ['structured_data', 'Structured data'],
  ['migration_qa', 'Migration QA'],
] as const;

const limitFields = [
  ['maximum_urls', 'Maximum URLs'],
  ['maximum_depth', 'Maximum depth'],
  ['maximum_duration_seconds', 'Maximum duration (seconds)'],
  ['maximum_accepted_bytes', 'Maximum accepted bytes'],
  ['maximum_concurrency', 'Maximum concurrency'],
  ['maximum_queue_size', 'Maximum queue size'],
  ['minimum_request_delay_seconds', 'Minimum request delay (seconds)'],
  ['maximum_redirect_hops', 'Maximum redirect hops'],
  ['maximum_response_bytes', 'Maximum response bytes'],
] as const;

const activeStates = new Set(['queued', 'running']);
const resultTabs = [
  ['summary', 'Summary'],
  ['pages', 'Pages'],
  ['issues', 'Issues'],
  ['sitemap', 'Sitemap'],
  ['exclusions', 'Exclusions'],
  ['evidence', 'Evidence'],
  ['settings', 'Settings Snapshot'],
  ['artifacts', 'Artifacts'],
] as const;

function messageFor(error: unknown): string {
  if (error instanceof ApiError)
    return `${error.message}${error.requestId ? ` Support reference: ${error.requestId}.` : ''}`;
  return error instanceof Error ? error.message : 'The request could not be completed.';
}

function tone(lifecycle: string): 'positive' | 'neutral' | 'warning' {
  if (lifecycle === 'completed') return 'positive';
  if (lifecycle.includes('failed') || lifecycle === 'cancelled') return 'warning';
  return 'neutral';
}

function formatDate(value: unknown): string {
  if (typeof value !== 'string' || !value) return 'Not available';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString();
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not available';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'bigint')
    return String(value);
  return 'Not available';
}

function withoutKey(values: Record<string, number>, key: string): Record<string, number> {
  return Object.fromEntries(Object.entries(values).filter(([name]) => name !== key));
}

function Breadcrumbs({ children }: { children: ReactNode }) {
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <Link to="/site-audits">Site Audits</Link>
      <span aria-hidden="true">/</span>
      {children}
    </nav>
  );
}

function LoadFailure({ error }: { error: string }) {
  return <ErrorState title="Site Audit unavailable">{error}</ErrorState>;
}

function LoadingAudit() {
  return (
    <Card aria-busy="true">
      <Spinner label="Loading Site Audit" /> Loading Site Audit…
    </Card>
  );
}

function useAuditDetail(auditId: string | undefined) {
  const [detail, setDetail] = useState<AuditDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    if (!auditId) return;
    try {
      setDetail(await siteAuditsApi.detail(auditId));
      setError(null);
    } catch (caught) {
      setError(messageFor(caught));
    }
  }, [auditId]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void reload();
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [reload]);
  return { detail, error, reload, setDetail };
}

export function SiteAuditHistoryPage() {
  const { can } = useAuth();
  const [parameters, setParameters] = useSearchParams();
  const [result, setResult] = useState<Awaited<ReturnType<typeof siteAuditsApi.history>> | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const offset = Math.max(0, Number(parameters.get('offset') ?? 0) || 0);
  const pageSize = [50, 100, 500].includes(Number(parameters.get('limit')))
    ? Number(parameters.get('limit'))
    : 50;
  const search = parameters.get('search') ?? '';
  const lifecycle = parameters.get('lifecycle') ?? '';

  useEffect(() => {
    let live = true;
    void siteAuditsApi.history({ offset, pageSize, search, lifecycle }).then(
      (value) => {
        if (live) {
          setResult(value);
          setError(null);
        }
      },
      (caught: unknown) => {
        if (live) setError(messageFor(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [lifecycle, offset, pageSize, search]);

  const update = (key: string, value: string, reset = true) => {
    const next = new URLSearchParams(parameters);
    if (value) next.set(key, value);
    else next.delete(key);
    if (reset) next.set('offset', '0');
    setParameters(next);
  };

  return (
    <>
      <PageHeader eyebrow="Combined Site Audit" title="Audit History">
        Resume drafts, monitor active audits, and inspect immutable completed results.
      </PageHeader>
      <div className="toolbar">
        {can('jobs.submit') ? (
          <>
            <Link className="button" to="/site-audits/new">
              New Site Audit
            </Link>
            <Link to="/settings?view=profiles">Saved Site Profiles</Link>
          </>
        ) : null}
        {can('settings.manage') ? (
          <Link to="/settings?view=global">Global Audit Settings</Link>
        ) : null}
      </div>
      <div className="filter-bar" aria-label="Audit history filters">
        <label>
          Search
          <input
            value={search}
            placeholder="Name, label, or seed URL"
            onChange={(event) => {
              update('search', event.target.value);
            }}
          />
        </label>
        <label>
          Status
          <select
            value={lifecycle}
            onChange={(event) => {
              update('lifecycle', event.target.value);
            }}
          >
            <option value="">All statuses</option>
            {lifecycleStates.map((state) => (
              <option key={state} value={state}>
                {state.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
        </label>
        <label>
          Rows
          <select
            value={pageSize}
            onChange={(event) => {
              update('limit', event.target.value);
            }}
          >
            {[50, 100, 500].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <Button
          type="button"
          onClick={() => {
            setParameters({});
          }}
        >
          Reset
        </Button>
      </div>
      {error ? <LoadFailure error={error} /> : null}
      {!result && !error ? <LoadingAudit /> : null}
      {result?.items.length === 0 ? (
        <EmptyState title="No Site Audits found">
          Create a Site Audit or adjust the filters.
        </EmptyState>
      ) : null}
      {result?.items.length ? (
        <>
          <TableFoundation>
            <thead>
              <tr>
                <th>Audit</th>
                <th>Website</th>
                <th>Status</th>
                <th>Completeness</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {result.items.map((audit) => (
                <tr key={audit.audit_id}>
                  <td>
                    <Link
                      to={
                        editableStates.has(audit.lifecycle) && can('jobs.submit')
                          ? `/site-audits/${audit.audit_id}/edit`
                          : `/site-audits/${audit.audit_id}`
                      }
                    >
                      {audit.audit_name}
                    </Link>
                    <small>{audit.audit_id}</small>
                  </td>
                  <td>
                    {audit.site_label ?? 'Unlabeled site'}
                    <small>{audit.normalized_seed_url}</small>
                  </td>
                  <td>
                    <StatusBadge tone={tone(audit.lifecycle)}>
                      {audit.lifecycle.replaceAll('_', ' ')}
                    </StatusBadge>
                  </td>
                  <td>
                    {audit.population_completeness} population
                    <small>{audit.module_completeness} modules</small>
                  </td>
                  <td>{formatDate(audit.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </TableFoundation>
          <Pagination
            offset={offset}
            pageSize={pageSize}
            total={result.total}
            onOffset={(value) => {
              update('offset', String(value), false);
            }}
          />
        </>
      ) : null}
    </>
  );
}

function Pagination({
  offset,
  pageSize,
  total,
  onOffset,
}: {
  offset: number;
  pageSize: number;
  total: number;
  onOffset: (value: number) => void;
}) {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(total, offset + pageSize);
  return (
    <nav className="pagination" aria-label="Pagination">
      <Button
        type="button"
        disabled={offset === 0}
        onClick={() => {
          onOffset(Math.max(0, offset - pageSize));
        }}
      >
        Previous
      </Button>
      <span aria-live="polite">
        {first.toLocaleString()}–{last.toLocaleString()} of {total.toLocaleString()}
      </span>
      <Button
        type="button"
        disabled={offset + pageSize >= total}
        onClick={() => {
          onOffset(offset + pageSize);
        }}
      >
        Next
      </Button>
    </nav>
  );
}

export function NewSiteAuditPage() {
  const { auditId } = useParams();
  const navigate = useNavigate();
  const [parameters, setParameters] = useSearchParams();
  const [draft, setDraft] = useState<SiteAuditDraft>(defaultDraft);
  const [audit, setAudit] = useState<AuditRecord | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [profiles, setProfiles] = useState<SiteProfile[]>([]);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const step = Math.min(7, Math.max(1, Number(parameters.get('step') ?? 1) || 1));

  useEffect(() => {
    void Promise.all([siteAuditSettingsApi.presets(), siteAuditSettingsApi.profiles()]).then(
      ([presetItems, profilePage]) => {
        setPresets(presetItems);
        setProfiles(profilePage.items);
      },
      () => undefined,
    );
  }, []);

  useEffect(() => {
    if (!auditId) return;
    let live = true;
    void siteAuditsApi.detail(auditId).then(
      (value) => {
        if (!live) return;
        setAudit(value.audit);
        setDraft(value.audit.draft);
        setDirty(false);
      },
      (caught: unknown) => {
        if (live) setError(messageFor(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [auditId]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => {
      window.removeEventListener('beforeunload', warn);
    };
  }, [dirty]);

  const patch = (value: Partial<SiteAuditDraft>) => {
    setDraft((current) => ({ ...current, ...value }));
    setDirty(true);
    setNotice(null);
  };

  const save = async (): Promise<AuditRecord> => {
    setBusy(true);
    setError(null);
    try {
      const saved = audit
        ? await siteAuditsApi.updateDraft(audit.audit_id, audit.revision, draft)
        : await siteAuditsApi.createDraft(draft, crypto.randomUUID());
      setAudit(saved);
      setDraft(saved.draft);
      setDirty(false);
      setNotice('Draft saved.');
      if (!auditId)
        await navigate(`/site-audits/${saved.audit_id}/edit?step=${String(step)}`, {
          replace: true,
        });
      return saved;
    } finally {
      setBusy(false);
    }
  };

  const saveAnd = async (operation: 'validate' | 'preflight') => {
    try {
      const saved = dirty || !audit ? await save() : audit;
      setBusy(true);
      const result = await siteAuditsApi[operation](saved.audit_id, saved.revision);
      const updated = result.audit as AuditRecord;
      setAudit(updated);
      setDraft(updated.draft);
      setNotice(operation === 'validate' ? 'Validation completed.' : 'Preflight completed.');
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  };

  const go = async (next: number) => {
    try {
      const creating = !auditId;
      const saved = dirty || !audit ? await save() : audit;
      if (creating) {
        await navigate(`/site-audits/${saved.audit_id}/edit?step=${String(next)}`, {
          replace: true,
        });
        return;
      }
      const nextParameters = new URLSearchParams(parameters);
      nextParameters.set('step', String(next));
      setParameters(nextParameters);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (caught) {
      setError(messageFor(caught));
    }
  };

  const submit = async () => {
    if (audit?.lifecycle !== 'ready') {
      setError('Validation and preflight must succeed before submission.');
      return;
    }
    if (!window.confirm('Submit this immutable Site Audit configuration?')) return;
    setBusy(true);
    try {
      await siteAuditsApi.action(audit.audit_id, 'submit');
      await navigate(`/site-audits/${audit.audit_id}`, { replace: true });
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Breadcrumbs>{audit ? audit.audit_name : 'New Site Audit'}</Breadcrumbs>
      <PageHeader
        eyebrow="Combined Site Audit"
        title={audit ? `Edit ${audit.audit_name}` : 'New Site Audit'}
      >
        Build a bounded, reviewable audit configuration. Each step is saved durably.
      </PageHeader>
      <ol className="wizard-steps" aria-label="Site Audit setup steps">
        {steps.map((label, index) => (
          <li key={label} className={step === index + 1 ? 'active' : ''}>
            <button
              type="button"
              onClick={() => void go(index + 1)}
              aria-current={step === index + 1 ? 'step' : undefined}
            >
              <span>{index + 1}</span> {label}
            </button>
          </li>
        ))}
      </ol>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert>{notice}</Alert> : null}
      <Card className="workflow-panel">
        <form
          className="workflow-form"
          onSubmit={(event) => {
            event.preventDefault();
            void go(Math.min(7, step + 1));
          }}
        >
          <WizardStep
            step={step}
            draft={draft}
            patch={patch}
            presets={presets}
            profiles={profiles}
          />
          <div className="wizard-actions">
            <Button type="button" disabled={step === 1 || busy} onClick={() => void go(step - 1)}>
              Back
            </Button>
            <Button
              type="button"
              disabled={busy || !draft.seed_url}
              onClick={() => {
                void save().catch((caught: unknown) => {
                  setError(messageFor(caught));
                });
              }}
            >
              Save draft
            </Button>
            {step < 7 ? (
              <Button type="submit" disabled={busy || !draft.seed_url}>
                Save and continue
              </Button>
            ) : (
              <>
                <Button type="button" disabled={busy} onClick={() => void saveAnd('validate')}>
                  Validate
                </Button>
                <Button
                  type="button"
                  disabled={
                    busy || !audit || !['validated', 'preflight_failed'].includes(audit.lifecycle)
                  }
                  onClick={() => void saveAnd('preflight')}
                >
                  Run preflight
                </Button>
                <Button
                  type="button"
                  disabled={busy || audit?.lifecycle !== 'ready'}
                  onClick={() => void submit()}
                >
                  Submit Site Audit
                </Button>
              </>
            )}
          </div>
        </form>
      </Card>
    </>
  );
}

function WizardStep({
  step,
  draft,
  patch,
  presets,
  profiles,
}: {
  step: number;
  draft: SiteAuditDraft;
  patch: (value: Partial<SiteAuditDraft>) => void;
  presets: Preset[];
  profiles: SiteProfile[];
}) {
  if (step === 1)
    return (
      <>
        <h2>Website</h2>
        <label>
          Audit name
          <input
            required
            maxLength={200}
            value={draft.audit_name}
            onChange={(event) => {
              patch({ audit_name: event.target.value });
            }}
          />
        </label>
        <label>
          Site label
          <input
            value={draft.site_label ?? ''}
            onChange={(event) => {
              patch({ site_label: event.target.value || null });
            }}
          />
        </label>
        <label>
          Seed URL
          <input
            type="url"
            required
            value={draft.seed_url}
            placeholder="https://example.com/"
            onChange={(event) => {
              patch({ seed_url: event.target.value });
            }}
          />
        </label>
        <label>
          Saved site profile (optional)
          <select
            value={draft.site_profile_id ?? ''}
            onChange={(event) => {
              const profile = profiles.find((item) => item.profile_id === event.target.value);
              patch(
                profile
                  ? {
                      site_profile_id: profile.profile_id,
                      site_profile_version: profile.current_version,
                      site_label: profile.site_label,
                      seed_url: profile.authorized_seed,
                    }
                  : { site_profile_id: null, site_profile_version: null },
              );
            }}
          >
            <option value="">No saved profile</option>
            {profiles.map((profile) => (
              <option key={profile.profile_id} value={profile.profile_id}>
                {profile.site_label} — {profile.authorized_seed}
              </option>
            ))}
          </select>
        </label>
      </>
    );
  if (step === 2)
    return (
      <>
        <h2>Platform and Preset</h2>
        <label>
          Platform preset
          <select
            value={draft.platform_preset_id ?? ''}
            onChange={(event) => {
              const preset = presets.find((item) => item.preset_id === event.target.value);
              patch({
                platform_preset_id: preset?.preset_id ?? null,
                platform_preset_version: preset?.version ?? null,
                preset_accepted: false,
              });
            }}
          >
            <option value="">No preset</option>
            {presets.map((preset) => (
              <option key={`${preset.preset_id}-${preset.version}`} value={preset.preset_id}>
                {preset.label} ({preset.version})
              </option>
            ))}
          </select>
        </label>
        {draft.platform_preset_id ? (
          <label className="check-control">
            <input
              type="checkbox"
              checked={draft.preset_accepted ?? false}
              onChange={(event) => {
                patch({ preset_accepted: event.target.checked });
              }}
            />
            <span>
              I reviewed and accept this preset’s URL-governance behavior.
              <small>Preset acceptance is retained in the immutable settings snapshot.</small>
            </span>
          </label>
        ) : (
          <Alert>No platform preset will be applied.</Alert>
        )}
      </>
    );
  if (step === 3)
    return (
      <>
        <h2>URL Governance</h2>
        <label>
          Crawl scope
          <select
            value={draft.scope_policy.mode}
            onChange={(event) => {
              patch({ scope_policy: { mode: event.target.value } });
            }}
          >
            <option value="exact_host">Exact host</option>
            <option value="approved_hosts">Approved hosts</option>
          </select>
        </label>
        <label>
          Approved hosts (one per line)
          <textarea
            value={draft.approved_hosts.join('\n')}
            onChange={(event) => {
              patch({
                approved_hosts: event.target.value
                  .split(/\r?\n/u)
                  .map((value) => value.trim())
                  .filter(Boolean),
              });
            }}
          />
        </label>
        <label className="check-control">
          <input
            type="checkbox"
            checked={draft.tracking_parameters_accepted}
            onChange={(event) => {
              patch({ tracking_parameters_accepted: event.target.checked });
            }}
          />
          <span>Strip accepted tracking parameters during URL normalization</span>
        </label>
        <label>
          Tracking parameters (one per line)
          <textarea
            value={draft.tracking_parameters.join('\n')}
            onChange={(event) => {
              patch({
                tracking_parameters: event.target.value
                  .split(/\r?\n/u)
                  .map((value) => value.trim())
                  .filter(Boolean),
              });
            }}
          />
        </label>
        <p>
          Detailed inherited and per-audit rule governance remains available in Saved Site Profiles
          and Global Audit Settings.
        </p>
      </>
    );
  if (step === 4)
    return (
      <>
        <h2>Crawl Limits</h2>
        <label>
          Crawl profile
          <select
            value={draft.crawl_profile}
            onChange={(event) => {
              patch({ crawl_profile: event.target.value });
            }}
          >
            <option value="quick_scan">Quick scan</option>
            <option value="standard_crawl">Standard crawl</option>
            <option value="deep_crawl">Deep crawl</option>
          </select>
        </label>
        <div className="override-grid">
          {limitFields.map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                min={key === 'minimum_request_delay_seconds' ? 0 : 1}
                step={key.includes('seconds') ? '0.1' : '1'}
                value={draft.crawl_limits[key] ?? ''}
                onChange={(event) => {
                  const next =
                    event.target.value === ''
                      ? withoutKey(draft.crawl_limits, key)
                      : { ...draft.crawl_limits, [key]: Number(event.target.value) };
                  patch({ crawl_limits: next });
                }}
              />
            </label>
          ))}
        </div>
        <small>Blank overrides use the selected bounded profile defaults.</small>
      </>
    );
  if (step === 5)
    return (
      <>
        <h2>Audit Modules</h2>
        <div className="option-grid">
          {modules.map(([key, label]) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={draft.enabled_modules.includes(key)}
                onChange={(event) => {
                  patch({
                    enabled_modules: event.target.checked
                      ? [...draft.enabled_modules, key]
                      : draft.enabled_modules.filter((value) => value !== key),
                  });
                }}
              />
              <span>{label}</span>
              <small>Runs only when retained crawl evidence supports this specialist.</small>
            </label>
          ))}
        </div>
      </>
    );
  if (step === 6)
    return (
      <>
        <h2>Thresholds</h2>
        <div className="override-grid">
          {(
            [
              ['title_minimum', 'Minimum title length'],
              ['title_maximum', 'Maximum title length'],
              ['description_minimum', 'Minimum description length'],
              ['description_maximum', 'Maximum description length'],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                min="1"
                value={draft.thresholds[key] ?? ''}
                onChange={(event) => {
                  const next = event.target.value
                    ? { ...draft.thresholds, [key]: Number(event.target.value) }
                    : withoutKey(draft.thresholds, key);
                  patch({ thresholds: next });
                }}
              />
            </label>
          ))}
        </div>
        <small>Blank thresholds inherit the effective global and site-profile settings.</small>
      </>
    );
  return (
    <>
      <h2>Review and Submit</h2>
      <Alert tone="warning">
        Submission creates an immutable snapshot. Review the target, scope, limits, modules, and
        governance before continuing.
      </Alert>
      <dl className="settings-breakdown">
        <Review label="Audit" value={draft.audit_name} />
        <Review label="Seed URL" value={draft.seed_url} />
        <Review label="Scope" value={draft.scope_policy.mode} />
        <Review label="Preset" value={draft.platform_preset_id ?? 'None'} />
        <Review label="Crawl profile" value={draft.crawl_profile} />
        <Review label="Modules" value={draft.enabled_modules.join(', ')} />
        <Review
          label="Approved hosts"
          value={draft.approved_hosts.join(', ') || 'Exact seed host only'}
        />
        <Review
          label="Crawl limits"
          value={Object.keys(draft.crawl_limits).length ? draft.crawl_limits : 'Profile defaults'}
        />
        <Review
          label="Thresholds"
          value={Object.keys(draft.thresholds).length ? draft.thresholds : 'Inherited defaults'}
        />
        <Review label="Publication" value="Disabled" />
      </dl>
    </>
  );
}

function Review({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{display(value)}</dd>
    </div>
  );
}

export function SiteAuditLifecyclePage() {
  const { auditId } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const { detail, error, reload } = useAuditDetail(auditId);
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!auditId || !detail || editableStates.has(detail.audit.lifecycle)) return;
    let live = true;
    const load = () =>
      void siteAuditsApi.status(auditId).then(
        (value) => {
          if (live) setStatus(value);
        },
        (caught: unknown) => {
          if (live) setActionError(messageFor(caught));
        },
      );
    load();
    if (!activeStates.has(detail.audit.lifecycle))
      return () => {
        live = false;
      };
    const timer = window.setInterval(() => {
      load();
      void reload();
    }, 2500);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [auditId, detail, reload]);

  if (error) return <LoadFailure error={error} />;
  if (!detail) return <LoadingAudit />;
  const audit = detail.audit;
  if (editableStates.has(audit.lifecycle) && can('jobs.submit'))
    return <NavigateToEdit audit={audit} />;
  const perform = async (action: 'cancel' | 'retry' | 'reconcile' | 'archive') => {
    if (!auditId) return;
    try {
      await siteAuditsApi.action(auditId, action);
      await reload();
    } catch (caught) {
      setActionError(messageFor(caught));
    }
  };
  return (
    <>
      <Breadcrumbs>{audit.audit_name}</Breadcrumbs>
      <PageHeader eyebrow="Site Audit lifecycle" title={audit.audit_name}>
        {audit.normalized_seed_url}
      </PageHeader>
      {actionError ? <Alert tone="error">{actionError}</Alert> : null}
      <div className="metric-grid">
        <Card>
          <span>Status</span>
          <strong>{audit.lifecycle.replaceAll('_', ' ')}</strong>
          <StatusBadge tone={tone(audit.lifecycle)}>
            {audit.partial ? 'Partial evidence' : 'Current state'}
          </StatusBadge>
        </Card>
        <Card>
          <span>Population</span>
          <strong>{audit.population_completeness}</strong>
          <small>Page inventory completeness</small>
        </Card>
        <Card>
          <span>Modules</span>
          <strong>{audit.module_completeness}</strong>
          <small>Specialist completion</small>
        </Card>
      </div>
      {audit.failure_explanation ? (
        <Alert tone="error">
          {audit.failure_explanation} ({audit.failure_code})
        </Alert>
      ) : null}
      <div className="toolbar">
        {['completed', 'completed_with_warnings', 'partially_completed'].includes(
          audit.lifecycle,
        ) ? (
          <Link className="button" to={`/site-audits/${audit.audit_id}/results/summary`}>
            View results
          </Link>
        ) : null}
        {activeStates.has(audit.lifecycle) && can('jobs.cancel') ? (
          <Button type="button" onClick={() => void perform('cancel')}>
            Cancel audit
          </Button>
        ) : null}
        {['failed', 'cancelled'].includes(audit.lifecycle) && can('jobs.submit') ? (
          <Button type="button" onClick={() => void perform('retry')}>
            Retry audit
          </Button>
        ) : null}
        {audit.lifecycle === 'recovery_required' && can('settings.manage') ? (
          <Button type="button" onClick={() => void perform('reconcile')}>
            Reconcile audit
          </Button>
        ) : null}
        {terminalStates.has(audit.lifecycle) &&
        can('settings.manage') &&
        audit.lifecycle !== 'archived' ? (
          <Button type="button" onClick={() => void perform('archive')}>
            Archive
          </Button>
        ) : null}
        <Button type="button" onClick={() => navigate('/site-audits')}>
          Audit History
        </Button>
      </div>
      <Card className="workflow-panel">
        <h2>Durable execution</h2>
        {status ? (
          <SafeProjection value={status} />
        ) : (
          <p>Execution details are not available yet.</p>
        )}
      </Card>
    </>
  );
}

function NavigateToEdit({ audit }: { audit: AuditRecord }) {
  const navigate = useNavigate();
  useEffect(() => {
    void navigate(`/site-audits/${audit.audit_id}/edit`, { replace: true });
  }, [audit.audit_id, navigate]);
  return <LoadingAudit />;
}

export function SiteAuditResultsPage() {
  const { auditId, tab = 'summary' } = useParams();
  const [parameters] = useSearchParams();
  const { detail, error } = useAuditDetail(auditId);
  if (error) return <LoadFailure error={error} />;
  if (!detail || !auditId) return <LoadingAudit />;
  return (
    <>
      <Breadcrumbs>
        <Link to={`/site-audits/${auditId}`}>{detail.audit.audit_name}</Link>
        <span aria-hidden="true">/</span> Results
      </Breadcrumbs>
      <PageHeader eyebrow="Combined Site Audit results" title={detail.audit.audit_name}>
        Retained, bounded evidence for {detail.audit.normalized_seed_url}.
      </PageHeader>
      <nav className="audit-tabs" aria-label="Site Audit result views">
        {resultTabs.map(([key, label]) => (
          <Link
            key={key}
            aria-current={tab === key ? 'page' : undefined}
            to={`/site-audits/${auditId}/results/${key}${parameters.toString() ? `?${parameters.toString()}` : ''}`}
          >
            {label}
          </Link>
        ))}
      </nav>
      <ResultTab auditId={auditId} tab={tab} />
    </>
  );
}

function ResultTab({ auditId, tab }: { auditId: string; tab: string }) {
  if (tab === 'pages') return <PagesResult auditId={auditId} />;
  if (tab === 'issues') return <IssuesResult auditId={auditId} />;
  if (tab === 'sitemap') return <SitemapResult auditId={auditId} />;
  if (tab === 'exclusions') return <ExclusionsResult auditId={auditId} />;
  if (tab === 'evidence') return <EvidenceResult auditId={auditId} />;
  if (tab === 'settings') return <SettingsSnapshotResult auditId={auditId} />;
  if (tab === 'artifacts') return <ArtifactsResult auditId={auditId} />;
  if (tab === 'summary')
    return <ProjectionResult title="Summary" load={() => siteAuditsApi.summary(auditId)} />;
  return (
    <EmptyState title="Unknown result view">Choose one of the available result tabs.</EmptyState>
  );
}

function ProjectionResult({ title, load }: { title: string; load: () => Promise<unknown> }) {
  const [value, setValue] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void load().then(
      (result) => {
        if (live) setValue(result);
      },
      (caught: unknown) => {
        if (live) setError(messageFor(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [load]);
  if (error) return <LoadFailure error={error} />;
  if (value === null) return <LoadingAudit />;
  return (
    <Card>
      <h2>{title}</h2>
      <SafeProjection value={value} />
    </Card>
  );
}

function SafeProjection({ value }: { value: unknown }) {
  const safe = JSON.stringify(
    value,
    (key, item: unknown) =>
      /body|raw_html|secret|token|password|filesystem|path_on_disk/iu.test(key)
        ? '[not retained]'
        : item,
    2,
  );
  return <pre className="safe-projection">{safe}</pre>;
}

function usePaging() {
  const [parameters, setParameters] = useSearchParams();
  const offset = Math.max(0, Number(parameters.get('offset') ?? 0) || 0);
  const requested = parameters.get('limit');
  const showAll = requested === 'all';
  const pageSize = [50, 100, 500].includes(Number(requested)) ? Number(requested) : 50;
  const set = (key: string, value: number) => {
    const next = new URLSearchParams(parameters);
    next.set(key, String(value));
    setParameters(next);
  };
  const setLimit = (value: number | 'all') => {
    const next = new URLSearchParams(parameters);
    next.set('limit', String(value));
    next.set('offset', '0');
    setParameters(next);
  };
  const setFilter = (key: string, value: string | boolean) => {
    const next = new URLSearchParams(parameters);
    if (value === '' || value === false) next.delete(key);
    else next.set(key, String(value));
    next.set('offset', '0');
    setParameters(next);
  };
  const reset = () => {
    setParameters(new URLSearchParams());
  };
  return { parameters, offset, pageSize, showAll, set, setLimit, setFilter, reset };
}

async function browserAll<T>(
  load: (offset: number, pageSize: number) => Promise<AuditPage<T>>,
): Promise<AuditPage<T>> {
  const items: T[] = [];
  let total = 0;
  while (items.length < 5000) {
    const page = await load(items.length, 500);
    total = page.total;
    items.push(...page.items.slice(0, 5000 - items.length));
    if (page.items.length === 0 || items.length >= total) break;
  }
  return { items, offset: 0, page_size: 500, total, ordering: 'server-stable paged sequence' };
}

function PagesResult({ auditId }: { auditId: string }) {
  const { parameters, offset, pageSize, showAll, set, setLimit, setFilter, reset } = usePaging();
  const [page, setPage] = useState<AuditPage<UrlRecord> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryString = parameters.toString();
  useEffect(() => {
    let live = true;
    const route = new URLSearchParams(queryString);
    const filters: PageFilters = {
      url: route.get('url') ?? undefined,
      http_status: route.get('http_status') ? Number(route.get('http_status')) : undefined,
      content_type: route.get('content_type') ?? undefined,
      fetch_state: route.get('fetch_state') ?? undefined,
      indexability: route.get('indexability') ?? undefined,
      canonical: route.get('canonical') ?? undefined,
      existing_sitemap: route.get('existing_sitemap') ?? undefined,
      recommended_sitemap: route.get('recommended_sitemap') ?? undefined,
      metadata_eligibility: route.get('metadata_eligibility') ?? undefined,
      issue_category: route.get('issue_category') ?? undefined,
      severity: route.get('severity') ?? undefined,
      business_importance: route.get('business_importance') ?? undefined,
      exclusion_reason: route.get('exclusion_reason') ?? undefined,
      query_parameter: route.get('query_parameter') === 'true' || undefined,
      crawl_depth: route.get('crawl_depth') ? Number(route.get('crawl_depth')) : undefined,
      partial: route.get('partial') === 'true' || undefined,
      only_actionable: route.get('only_actionable') === 'true' || undefined,
      only_sitemap_issues: route.get('only_sitemap_issues') === 'true' || undefined,
      only_metadata_issues: route.get('only_metadata_issues') === 'true' || undefined,
      only_excluded: route.get('only_excluded') === 'true' || undefined,
      sort: route.get('sort') ?? undefined,
      direction: route.get('direction') === 'desc' ? 'desc' : 'asc',
    };
    const request = showAll
      ? browserAll((pageOffset, limit) => siteAuditsApi.pages(auditId, pageOffset, limit, filters))
      : siteAuditsApi.pages(auditId, offset, pageSize, filters);
    void request.then(
      (value) => {
        if (live) setPage(value);
      },
      (caught: unknown) => {
        if (live) setError(messageFor(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [auditId, offset, pageSize, queryString, showAll]);
  if (error) return <LoadFailure error={error} />;
  if (!page) return <LoadingAudit />;
  return (
    <Card>
      <div className="card-heading">
        <h2>Pages</h2>
        <PageSize value={showAll ? 'all' : pageSize} onChange={setLimit} />
      </div>
      <details className="filter-panel" open>
        <summary>Filter and sort pages</summary>
        <div className="filter-bar">
          <ResultInput label="URL contains" name="url" parameters={parameters} set={setFilter} />
          <ResultInput
            label="HTTP status"
            name="http_status"
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Content type"
            name="content_type"
            options={['text/html', 'application/pdf']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Fetch state"
            name="fetch_state"
            options={['fetched', 'failed', 'not_fetched']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Indexability"
            name="indexability"
            options={['indexable', 'noindex', 'indeterminate']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Canonical"
            name="canonical"
            options={['self_canonical', 'canonicalized_elsewhere', 'missing', 'indeterminate']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Existing sitemap"
            name="existing_sitemap"
            options={['present', 'absent', 'indeterminate']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Recommended sitemap"
            name="recommended_sitemap"
            options={['include', 'exclude', 'review', 'indeterminate']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Metadata eligibility"
            name="metadata_eligibility"
            options={['include_in_metadata_scoring', 'exclude_from_metadata_scoring']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultInput
            label="Issue category"
            name="issue_category"
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Severity"
            name="severity"
            options={['critical', 'high', 'medium', 'low', 'informational']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Business importance"
            name="business_importance"
            options={['critical', 'high', 'standard', 'low']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultInput
            label="Exclusion reason"
            name="exclusion_reason"
            parameters={parameters}
            set={setFilter}
          />
          <ResultInput
            label="Crawl depth"
            name="crawl_depth"
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Sort"
            name="sort"
            options={['sequence', 'url', 'status', 'severity', 'depth', 'issues']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Direction"
            name="direction"
            options={['asc', 'desc']}
            parameters={parameters}
            set={setFilter}
          />
          {[
            'query_parameter',
            'partial',
            'only_actionable',
            'only_sitemap_issues',
            'only_metadata_issues',
            'only_excluded',
            'show_optional',
          ].map((name) => (
            <label key={name}>
              <input
                type="checkbox"
                checked={parameters.get(name) === 'true'}
                onChange={(event) => {
                  setFilter(name, event.target.checked);
                }}
              />{' '}
              {name.replaceAll('_', ' ')}
            </label>
          ))}
          <Button type="button" onClick={reset}>
            Clear filters
          </Button>
        </div>
      </details>
      <TableFoundation>
        <thead>
          <tr>
            <th scope="col">URL</th>
            <th scope="col">Fetch / HTTP</th>
            <th scope="col">Governance</th>
            <th scope="col">Evidence</th>
            <th scope="col">Final URL</th>
            <th scope="col">Discovery</th>
            <th scope="col">Content</th>
            <th scope="col">Indexability</th>
            <th scope="col">Robots</th>
            <th scope="col">Canonical</th>
            <th scope="col">Sitemaps</th>
            <th scope="col">Metadata eligible</th>
            <th scope="col">Metadata</th>
            <th scope="col">Issues</th>
            <th scope="col">Importance</th>
            <th scope="col">Depth / links</th>
            <th scope="col">Rule or exclusion</th>
            {parameters.get('show_optional') === 'true' ? (
              <th scope="col">Optional evidence</th>
            ) : null}
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {page.items.map((item) => (
            <tr key={item.url_id}>
              <td>
                <Link
                  to={`/site-audits/${auditId}/results/pages/${String(item.sequence)}?return=${encodeURIComponent(parameters.toString())}`}
                >
                  {item.normalized_url}
                </Link>
                <small>Sequence {item.sequence}</small>
              </td>
              <td>
                {item.http_status ?? '—'}
                <small>{item.fetch_outcome}</small>
              </td>
              <td>
                {item.discovery_decision}
                <small>{item.sitemap_policy_decision}</small>
              </td>
              <td>{item.partial ? 'Partial' : 'Complete'}</td>
              <td className="wrap-anywhere">{display(item.final_url)}</td>
              <td>
                {display(item.discovery_state)}
                <small>{display(item.discovery_decision)}</small>
              </td>
              <td>{display(item.content_type)}</td>
              <td>{display(item.indexability_state)}</td>
              <td>{display(item.robots_state)}</td>
              <td>{display(item.canonical_state)}</td>
              <td>
                {display(item.existing_sitemap_state)}
                <small>Recommended: {display(item.recommended_sitemap_state)}</small>
              </td>
              <td>{display(item.metadata_scoring_decision)}</td>
              <td>
                Title: {display(item.title)}
                <small>
                  Length: {display(item.title_length)} · Description: {display(item.description)} ·
                  Length: {display(item.description_length)}
                </small>
              </td>
              <td>
                {display(item.issue_count)}
                <small>{display(item.highest_severity)}</small>
              </td>
              <td>{display(item.business_importance)}</td>
              <td>
                {display(item.crawl_depth)}
                <small>{display(item.inbound_link_count)} inbound</small>
              </td>
              <td>{display(item.primary_rule ?? item.failure_code)}</td>
              {parameters.get('show_optional') === 'true' ? (
                <td className="wrap-anywhere">
                  Original: {display(item.original_url)}
                  <small>
                    Redirects: {display(item.redirect_count)} · Meta robots:{' '}
                    {display(item.meta_robots)} · X-Robots: {display(item.x_robots_tag)} · Title
                    group: {display(item.duplicate_title_group)} · Description group:{' '}
                    {display(item.duplicate_description_group)} · Structured data:{' '}
                    {display(item.structured_data_types)} · Images: {display(item.image_count)} ·
                    Broken inbound: {display(item.broken_inbound_links)} · Source:{' '}
                    {display(item.discovery_source)} · Evidence: {display(item.evidence_id)}
                  </small>
                </td>
              ) : null}
              <td>
                <Link
                  to={`/site-audits/${auditId}/results/pages/${String(item.sequence)}?return=${encodeURIComponent(parameters.toString())}`}
                >
                  Review details
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </TableFoundation>
      {showAll ? (
        <p>
          Showing {page.items.length.toLocaleString()} of {page.total.toLocaleString()} through
          bounded 500-row requests{page.total > 5000 ? ' (browser maximum 5,000)' : ''}.
        </p>
      ) : (
        <Pagination
          offset={offset}
          pageSize={pageSize}
          total={page.total}
          onOffset={(value) => {
            set('offset', value);
          }}
        />
      )}
    </Card>
  );
}

function IssuesResult({ auditId }: { auditId: string }) {
  const { parameters, offset, pageSize, showAll, set, setLimit, setFilter, reset } = usePaging();
  const [page, setPage] = useState<AuditPage<IssueRecord> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryString = parameters.toString();
  useEffect(() => {
    let live = true;
    const route = new URLSearchParams(queryString);
    const filters: IssueFilters = {
      search: route.get('search') ?? undefined,
      category: route.get('category') ?? undefined,
      module: route.get('module') ?? undefined,
      severity: route.get('severity') ?? undefined,
      priority: route.get('priority') ?? undefined,
      business_importance: route.get('business_importance') ?? undefined,
      sitemap_impact: route.get('sitemap_impact') === 'true' || undefined,
      metadata_impact: route.get('metadata_impact') === 'true' || undefined,
      indexability_impact: route.get('indexability_impact') === 'true' || undefined,
      confidence: route.get('confidence') ?? undefined,
      determinacy: route.get('determinacy') ?? undefined,
      actionable: route.get('actionable') === 'true' || undefined,
    };
    const request = showAll
      ? browserAll((pageOffset, limit) => siteAuditsApi.issues(auditId, pageOffset, limit, filters))
      : siteAuditsApi.issues(auditId, offset, pageSize, filters);
    void request.then(
      (value) => {
        if (live) setPage(value);
      },
      (caught: unknown) => {
        if (live) setError(messageFor(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [auditId, offset, pageSize, queryString, showAll]);
  if (error) return <LoadFailure error={error} />;
  if (!page) return <LoadingAudit />;
  return (
    <Card>
      <div className="card-heading">
        <h2>Issues</h2>
        <PageSize value={showAll ? 'all' : pageSize} onChange={setLimit} />
      </div>
      <details className="filter-panel" open>
        <summary>Filter issues</summary>
        <div className="filter-bar">
          <ResultInput label="Search" name="search" parameters={parameters} set={setFilter} />
          <ResultInput label="Category" name="category" parameters={parameters} set={setFilter} />
          <ResultSelect
            label="Module"
            name="module"
            options={modules.map(([key]) => key)}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Severity"
            name="severity"
            options={['critical', 'high', 'medium', 'low', 'informational']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Priority"
            name="priority"
            options={['critical', 'high', 'medium', 'low']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Business importance"
            name="business_importance"
            options={['critical', 'high', 'standard', 'low']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Confidence"
            name="confidence"
            options={['high', 'medium', 'low']}
            parameters={parameters}
            set={setFilter}
          />
          <ResultSelect
            label="Determinacy"
            name="determinacy"
            options={['determinate', 'indeterminate']}
            parameters={parameters}
            set={setFilter}
          />
          {['sitemap_impact', 'metadata_impact', 'indexability_impact', 'actionable'].map(
            (name) => (
              <label key={name}>
                <input
                  type="checkbox"
                  checked={parameters.get(name) === 'true'}
                  onChange={(event) => {
                    setFilter(name, event.target.checked);
                  }}
                />{' '}
                {name.replaceAll('_', ' ')}
              </label>
            ),
          )}
          <Button type="button" onClick={reset}>
            Clear filters
          </Button>
        </div>
      </details>
      <TableFoundation>
        <thead>
          <tr>
            <th scope="col">Issue</th>
            <th scope="col">Code / module</th>
            <th scope="col">Severity / priority</th>
            <th scope="col">Priority explanation</th>
            <th scope="col">Affected URLs</th>
            <th scope="col">Importance</th>
            <th scope="col">Impacts</th>
            <th scope="col">Confidence</th>
            <th scope="col">Pattern</th>
            <th scope="col">Recommended action</th>
            <th scope="col">Sample URLs</th>
          </tr>
        </thead>
        <tbody>
          {page.items.map((item) => (
            <tr key={item.group_id}>
              <td>
                <Link
                  to={`/site-audits/${auditId}/results/issues/${item.group_id}?return=${encodeURIComponent(parameters.toString())}`}
                >
                  {item.title}
                </Link>
                <small>{item.category}</small>
              </td>
              <td>
                {display(item.code)}
                <small>{display(item.modules)}</small>
              </td>
              <td>
                {item.severity}
                <small>{display(item.priority_band)}</small>
              </td>
              <td className="wrap-anywhere">{display(item.priority_explanation)}</td>
              <td>
                {item.affected_url_count}
                <small>{item.finding_count} findings</small>
              </td>
              <td>{display(item.highest_business_importance)}</td>
              <td>
                Sitemap: {display(item.sitemap_impact)}
                <small>
                  Metadata: {display(item.metadata_impact)} · Indexability:{' '}
                  {display(item.indexability_impact)} · Links: {display(item.internal_link_impact)}
                </small>
              </td>
              <td>
                {display(item.confidence)}
                <small>{display(item.determinacy)}</small>
              </td>
              <td>{display(item.pattern_state)}</td>
              <td className="wrap-anywhere">{display(item.recommended_action)}</td>
              <td className="wrap-anywhere">{display(item.sample_urls_json)}</td>
            </tr>
          ))}
        </tbody>
      </TableFoundation>
      {showAll ? (
        <p>
          Showing {page.items.length.toLocaleString()} of {page.total.toLocaleString()} through
          bounded requests{page.total > 5000 ? ' (browser maximum 5,000)' : ''}.
        </p>
      ) : (
        <Pagination
          offset={offset}
          pageSize={pageSize}
          total={page.total}
          onOffset={(value) => {
            set('offset', value);
          }}
        />
      )}
    </Card>
  );
}

function ResultInput({
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

function ResultSelect({
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
            {option.replaceAll('_', ' ')}
          </option>
        ))}
      </select>
    </label>
  );
}

function PageSize({
  value,
  onChange,
}: {
  value: number | 'all';
  onChange: (value: number | 'all') => void;
}) {
  return (
    <label>
      Rows{' '}
      <select
        value={value}
        onChange={(event) => {
          onChange(event.target.value === 'all' ? 'all' : Number(event.target.value));
        }}
      >
        {[50, 100, 500].map((size) => (
          <option key={size}>{size}</option>
        ))}
        <option value="all">All (up to 5,000)</option>
      </select>
    </label>
  );
}

function DetailFields({ values }: { values: [string, unknown][] }) {
  return (
    <dl className="detail-list">
      {values.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className="wrap-anywhere">{display(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function RetainedRecords({ title, value }: { title: string; value: unknown }) {
  const records = Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  return (
    <details>
      <summary>
        {title} ({records.length})
      </summary>
      {records.length ? (
        <div className="structured-list">
          {records.map((record, index) => (
            <DetailFields
              key={display(record.id ?? record.finding_id ?? record.match_id ?? index)}
              values={Object.entries(record).filter(
                ([key]) =>
                  !/body|raw_html|secret|token|password|filesystem|path_on_disk/iu.test(key),
              )}
            />
          ))}
        </div>
      ) : (
        <p>No retained records.</p>
      )}
    </details>
  );
}

export function SiteAuditPageDetailPage() {
  const { auditId, sequence } = useParams();
  const [parameters] = useSearchParams();
  const [value, setValue] = useState<UrlRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!auditId || !sequence) return;
    let live = true;
    void siteAuditsApi.page(auditId, Number(sequence)).then(
      (result) => {
        if (live) setValue(result);
      },
      (caught: unknown) => {
        if (live) setError(messageFor(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [auditId, sequence]);
  if (error) return <LoadFailure error={error} />;
  if (!value || !auditId) return <LoadingAudit />;
  const external = safeHttpUrl(value.final_url ?? value.normalized_url);
  const back = parameters.get('return') ?? '';
  return (
    <>
      <Breadcrumbs>
        <Link to={`/site-audits/${auditId}/results/pages${back ? `?${back}` : ''}`}>Pages</Link>
        <span aria-hidden="true">/</span> URL {sequence}
      </Breadcrumbs>
      <PageHeader eyebrow="URL evidence" title={value.normalized_url}>
        Retained page-level decisions and evidence.
      </PageHeader>
      <div className="toolbar">
        {external ? (
          <a className="button" href={external} target="_blank" rel="noopener noreferrer">
            Open crawled URL in new tab
          </a>
        ) : (
          <Button disabled>Unsafe URL unavailable</Button>
        )}
        <Button
          type="button"
          onClick={() => {
            const original = value.original_url ?? value.requested_url;
            if (typeof original === 'string') void navigator.clipboard.writeText(original);
          }}
        >
          Copy original URL
        </Button>
        <Button
          type="button"
          onClick={() => void navigator.clipboard.writeText(value.normalized_url)}
        >
          Copy normalized URL
        </Button>
        <Button
          type="button"
          disabled={!value.final_url}
          onClick={() => void navigator.clipboard.writeText(String(value.final_url))}
        >
          Copy final URL
        </Button>
      </div>
      <div className="result-stack">
        <Card>
          <h2>URL and fetch evidence</h2>
          <DetailFields
            values={[
              ['Original URL', value.original_url],
              ['Requested URL', value.requested_url],
              ['Normalized URL', value.normalized_url],
              ['Final URL', value.final_url],
              ['Discovery decision', value.discovery_decision],
              ['Discovery state', value.discovery_state],
              ['Enqueued state', value.enqueued_state],
              ['Fetch state', value.fetch_state],
              ['Parse state', value.parse_state],
              ['HTTP status', value.http_status],
              ['Content type', value.content_type],
              ['Fetch outcome', value.fetch_outcome],
              ['Redirect state', value.redirect_state],
              ['Failure', value.failure_code],
              ['Partial evidence', value.partial],
              ['Evidence identifier', value.evidence_id],
            ]}
          />
        </Card>
        <Card>
          <h2>Search and governance evidence</h2>
          <DetailFields
            values={[
              ['Robots', value.robots_state],
              ['Indexability', value.indexability_state],
              ['Canonical', value.canonical_state],
              ['Existing sitemap', value.existing_sitemap_state],
              ['Recommended sitemap', value.recommended_sitemap_state],
              ['Metadata-scoring eligibility', value.metadata_scoring_decision],
              ['Sitemap policy', value.sitemap_policy_decision],
              ['Business importance', value.business_importance],
              ['Crawl depth', value.crawl_depth],
              ['Inbound links', value.inbound_link_count],
              ['Outbound links', value.outbound_link_count],
              ['Issue count', value.issue_count],
              ['Highest severity', value.highest_severity],
            ]}
          />
        </Card>
        <Card>
          <h2>Metadata and specialist summaries</h2>
          <DetailFields
            values={[
              ['Title', value.title],
              ['Meta description', value.description],
              ['Meta robots', value.meta_robots],
              ['X-Robots-Tag', value.x_robots_tag],
              ['Link summary', value.link_summary],
              ['Image summary', value.image_summary],
              ['Structured-data summary', value.structured_data_summary],
            ]}
          />
        </Card>
        <Card>
          <h2>Related retained records</h2>
          <RetainedRecords title="Discovery sources" value={value.discoveries} />
          <RetainedRecords title="Population memberships" value={value.populations} />
          <RetainedRecords
            title="Primary and contributing rule matches"
            value={value.rule_matches}
          />
          <RetainedRecords title="Findings" value={value.findings} />
          <DetailFields values={[['Issue-group memberships', value.issue_group_ids]]} />
        </Card>
      </div>
    </>
  );
}

export function SiteAuditIssueDetailPage() {
  const { auditId, groupId } = useParams();
  const [parameters, setParameters] = useSearchParams();
  const [value, setValue] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const membershipOffset = Math.max(0, Number(parameters.get('membership_offset') ?? 0) || 0);
  useEffect(() => {
    if (!auditId || !groupId) return;
    let live = true;
    void siteAuditsApi.issue(auditId, groupId, membershipOffset, 50).then(
      (result) => {
        if (live) setValue(result);
      },
      (caught: unknown) => {
        if (live) setError(messageFor(caught));
      },
    );
    return () => {
      live = false;
    };
  }, [auditId, groupId, membershipOffset]);
  if (error) return <LoadFailure error={error} />;
  if (!value || !auditId) return <LoadingAudit />;
  const back = parameters.get('return') ?? '';
  return (
    <>
      <Breadcrumbs>
        <Link to={`/site-audits/${auditId}/results/issues${back ? `?${back}` : ''}`}>Issues</Link>
        <span aria-hidden="true">/</span> Issue detail
      </Breadcrumbs>
      <PageHeader
        eyebrow="Issue evidence"
        title={display(value.title ?? (value.group as Record<string, unknown> | undefined)?.title)}
      >
        Retained findings and affected URL evidence.
      </PageHeader>
      <div className="result-stack">
        <Card>
          <h2>Issue definition and priority</h2>
          <DetailFields
            values={[
              ['Group identity', value.group_id],
              ['Title', value.title],
              ['Explanation', value.explanation],
              ['Category', value.category],
              ['Code', value.code],
              ['Applicable population', value.applicable_population],
              ['Severity', value.severity],
              ['Priority', value.priority_band],
              ['Priority explanation', value.priority_explanation],
              ['Recommended action', value.recommended_action],
              ['Full affected count', value.affected_url_count],
              ['Business importance', value.highest_business_importance],
              ['Sitemap impact', value.sitemap_impact],
              ['Metadata impact', value.metadata_impact],
              ['Indexability impact', value.indexability_impact],
              ['Internal-link impact', value.internal_link_impact],
              ['Confidence', value.confidence],
              ['Determinacy', value.determinacy],
              ['Pattern candidate', value.pattern_state],
              ['Sample URLs (not full membership)', value.sample_urls_json],
              ['Projection version', value.projection_version],
            ]}
          />
        </Card>
        <Card>
          <h2>Complete affected membership</h2>
          {Array.isArray(value.memberships) && value.memberships.length ? (
            <div className="structured-list">
              {(value.memberships as Record<string, unknown>[]).map((membership) => (
                <article key={String(membership.id)}>
                  <DetailFields
                    values={[
                      ['Membership reason', membership.membership_reason],
                      ['Sequence', membership.sequence],
                      ['URL', (membership.url as Record<string, unknown> | null)?.normalized_url],
                      ['Finding code', (membership.finding as Record<string, unknown>).code],
                      [
                        'Finding severity',
                        (membership.finding as Record<string, unknown>).severity,
                      ],
                      [
                        'Finding explanation',
                        (membership.finding as Record<string, unknown>).explanation,
                      ],
                      [
                        'Finding provenance',
                        (membership.finding as Record<string, unknown>).evidence_reference,
                      ],
                    ]}
                  />
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="No retained memberships">
              The full membership is unavailable for this issue group.
            </EmptyState>
          )}
          <Pagination
            offset={membershipOffset}
            pageSize={50}
            total={Number(value.total ?? 0)}
            onOffset={(next) => {
              const updated = new URLSearchParams(parameters);
              updated.set('membership_offset', String(next));
              setParameters(updated);
            }}
          />
        </Card>
      </div>
    </>
  );
}
