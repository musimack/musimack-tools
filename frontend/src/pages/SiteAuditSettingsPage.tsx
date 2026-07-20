import { useEffect, useMemo, useState, type SyntheticEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import {
  Alert,
  Button,
  Card,
  ErrorState,
  PageHeader,
  Spinner,
  StatusBadge,
  TableFoundation,
} from '../design-system/components';
import { ApiError } from '../api/client';
import { siteAuditSettingsApi } from '../site-audit-settings/api';
import {
  platformPresetIds,
  ruleActions,
  ruleMatchTypes,
  type EffectiveSettings,
  type GlobalConfiguration,
  type GlobalSettings,
  type GovernanceRequest,
  type PlatformPresetId,
  type Preset,
  type ProfilePage,
  type RuleAction,
  type RuleMatchType,
  type RuleTestResult,
  type SiteProfile,
  type SiteProfileConfiguration,
  type UrlRule,
} from '../site-audit-settings/contracts';

const emptyProfile = (): SiteProfileConfiguration => ({
  site_label: '',
  authorized_seed: '',
  approved_hosts: [],
  preset_id: null,
  preset_version: null,
  preset_accepted: false,
  preset_rule_states: {},
  tracking_parameters_accepted: false,
  tracking_parameter_exceptions: [],
  rules: [],
  crawl_profile: 'standard_crawl',
  crawl_limit_overrides: {},
  metadata_thresholds: {},
  enabled_modules: { images: true, structured_data: true },
  business_importance: [],
});

const emptyRule = (): UrlRule => ({
  rule_id: 'audit.sample_rule',
  name: 'Sample URL review',
  description: 'Temporary rule used only for this effective-settings preview.',
  enabled: true,
  match_type: 'path_starts_with',
  match_value: '/private/',
  case_sensitive: true,
  action: 'crawl_and_mark_for_review',
  reason: 'Review this URL family for the current audit.',
  reason_code: 'audit_sample_review',
  priority: 100,
  overrides_rule_ids: [],
});

const readable = (value: string) => value.replaceAll('_', ' ');
const message = (reason: unknown) =>
  reason instanceof ApiError ? reason.message : 'The settings request could not be completed.';
const stringRecord = (value: unknown): Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const textValue = (value: unknown): string =>
  typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value)
    : '';
const thresholdFields = [
  ['title_minimum', 'Title minimum'],
  ['title_maximum', 'Title maximum'],
  ['description_minimum', 'Description minimum'],
  ['description_maximum', 'Description maximum'],
] as const;

function governanceRequest(
  profileId: string,
  preset: Preset | undefined,
  accepted: boolean,
  ruleStates: Record<string, boolean>,
  trackingAccepted: boolean,
  trackingExceptions: string,
  disabledRuleIds: string,
  rule: UrlRule,
  samples: string,
): GovernanceRequest {
  return {
    profile_id: profileId || null,
    preset_id: preset?.preset_id ?? null,
    preset_version: preset?.version ?? null,
    preset_accepted: accepted,
    preset_rule_states: ruleStates,
    tracking_parameters_accepted: trackingAccepted,
    tracking_parameter_exceptions: trackingExceptions
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
    overrides: {
      rules: [rule],
      disabled_rule_ids: disabledRuleIds
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    },
    sample_urls: samples
      .split(/\r?\n/u)
      .map((item) => item.trim())
      .filter(Boolean),
  };
}

export function SiteAuditSettingsPage() {
  const { can } = useAuth();
  const administrator = can('settings.manage');
  const [search, setSearch] = useSearchParams();
  const selectedProfileId = search.get('profile') ?? '';
  const selectedPresetId = search.get('preset') ?? '';
  const [settings, setSettings] = useState<GlobalSettings | null>(null);
  const [globalDraft, setGlobalDraft] = useState<GlobalConfiguration | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [profiles, setProfiles] = useState<ProfilePage | null>(null);
  const [profileDraft, setProfileDraft] = useState<SiteProfileConfiguration>(emptyProfile);
  const [editingProfile, setEditingProfile] = useState<SiteProfile | null>(null);
  const [rule, setRule] = useState<UrlRule>(emptyRule);
  const [samples, setSamples] = useState('https://example.com/private/page\nhttps://example.com/');
  const [accepted, setAccepted] = useState(false);
  const [trackingAccepted, setTrackingAccepted] = useState(false);
  const [trackingExceptions, setTrackingExceptions] = useState('');
  const [disabledRuleIds, setDisabledRuleIds] = useState('');
  const [ruleStates, setRuleStates] = useState<Record<string, boolean>>({});
  const [effective, setEffective] = useState<EffectiveSettings | null>(null);
  const [testResult, setTestResult] = useState<RuleTestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedPreset = presets.find((item) => item.preset_id === selectedPresetId);
  const profilePreset = presets.find((item) => item.preset_id === profileDraft.preset_id);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextPresets, nextProfiles, nextSettings] = await Promise.all([
        siteAuditSettingsApi.presets(),
        siteAuditSettingsApi.profiles(administrator),
        administrator ? siteAuditSettingsApi.settings() : Promise.resolve(null),
      ]);
      setPresets(nextPresets);
      setProfiles(nextProfiles);
      setSettings(nextSettings);
      setGlobalDraft(nextSettings?.configuration ?? null);
      const initialProfile = nextProfiles.items.find(
        (item) => item.profile_id === selectedProfileId,
      );
      if (initialProfile) {
        const configuration = initialProfile.configuration;
        if (configuration.preset_id) {
          setSearch((current) => {
            const next = new URLSearchParams(current);
            next.set('preset', configuration.preset_id ?? '');
            return next;
          });
        }
        setAccepted(configuration.preset_accepted);
        setTrackingAccepted(configuration.tracking_parameters_accepted);
        setTrackingExceptions(configuration.tracking_parameter_exceptions.join(', '));
        setRuleStates(configuration.preset_rule_states);
      }
    } catch (reason) {
      setError(message(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // The asynchronous loader owns this resource's loading and result state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    // The permission boundary is stable for the authenticated route lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administrator]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => {
      window.removeEventListener('beforeunload', warn);
    };
  }, [dirty]);

  const request = useMemo(
    () =>
      governanceRequest(
        selectedProfileId,
        selectedPreset,
        accepted,
        ruleStates,
        trackingAccepted,
        trackingExceptions,
        disabledRuleIds,
        rule,
        samples,
      ),
    [
      accepted,
      disabledRuleIds,
      rule,
      ruleStates,
      samples,
      selectedPreset,
      selectedProfileId,
      trackingAccepted,
      trackingExceptions,
    ],
  );

  const updateQuery = (name: 'profile' | 'preset', value: string) => {
    setSearch((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(name, value);
      else next.delete(name);
      return next;
    });
    if (name === 'preset') {
      setAccepted(false);
      setTrackingAccepted(false);
      setRuleStates({});
    }
    if (name === 'profile' && !value) {
      setAccepted(false);
      setTrackingAccepted(false);
      setTrackingExceptions('');
      setRuleStates({});
    } else if (name === 'profile') {
      const profile = profiles?.items.find((item) => item.profile_id === value);
      if (profile) {
        const configuration = profile.configuration;
        if (configuration.preset_id) {
          setSearch((current) => {
            const next = new URLSearchParams(current);
            next.set('profile', value);
            next.set('preset', configuration.preset_id ?? '');
            return next;
          });
        }
        setAccepted(configuration.preset_accepted);
        setTrackingAccepted(configuration.tracking_parameters_accepted);
        setTrackingExceptions(configuration.tracking_parameter_exceptions.join(', '));
        setRuleStates(configuration.preset_rule_states);
      }
    }
    setEffective(null);
    setTestResult(null);
  };

  const preview = async () => {
    setError(null);
    try {
      setEffective(await siteAuditSettingsApi.effectiveSettings(request));
    } catch (reason) {
      setError(message(reason));
    }
  };

  const testRules = async () => {
    setError(null);
    const sampleCount = request.sample_urls?.length ?? 0;
    if (sampleCount < 1 || sampleCount > 100) {
      setError('Enter between 1 and 100 sample URLs.');
      return;
    }
    try {
      const result = await siteAuditSettingsApi.testRules(request);
      setTestResult(result);
      setEffective(result.effective_settings);
    } catch (reason) {
      setError(message(reason));
    }
  };

  const saveGlobal = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!globalDraft || !settings) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await siteAuditSettingsApi.updateSettings(globalDraft, settings.version);
      setSettings(saved);
      setGlobalDraft(saved.configuration);
      setDirty(false);
      setNotice(`Global settings version ${String(saved.version)} saved.`);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setSaving(false);
    }
  };

  const saveProfile = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const saved = editingProfile
        ? await siteAuditSettingsApi.updateProfile(
            editingProfile.profile_id,
            profileDraft,
            editingProfile.current_version,
          )
        : await siteAuditSettingsApi.createProfile(profileDraft);
      setNotice(`${saved.site_label} version ${String(saved.current_version)} saved.`);
      setProfileDraft(emptyProfile());
      setEditingProfile(null);
      setDirty(false);
      await load();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setSaving(false);
    }
  };

  const profileState = async (profile: SiteProfile, action: 'disable' | 'archive') => {
    setError(null);
    try {
      if (action === 'archive' && !window.confirm(`Archive ${profile.site_label}?`)) return;
      await (action === 'disable'
        ? siteAuditSettingsApi.disableProfile(profile.profile_id)
        : siteAuditSettingsApi.archiveProfile(profile.profile_id));
      setNotice(`${profile.site_label} is ${action === 'disable' ? 'disabled' : 'archived'}.`);
      await load();
    } catch (reason) {
      setError(message(reason));
    }
  };

  if (loading)
    return (
      <Card>
        <Spinner label="Loading Site Audit Settings" />
      </Card>
    );
  if (error && !presets.length)
    return <ErrorState title="Site Audit Settings are unavailable">{error}</ErrorState>;

  return (
    <>
      <PageHeader eyebrow="Combined Site Audit" title="Site Audit Settings">
        Review versioned presets and profiles, resolve temporary settings, and test bounded URL
        rules without crawling or creating an audit.
      </PageHeader>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert>{notice}</Alert> : null}
      {dirty ? <Alert tone="warning">You have unsaved administrator changes.</Alert> : null}

      {administrator && globalDraft && settings ? (
        <Card className="workflow-panel">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Administrator</p>
              <h2>Global defaults</h2>
            </div>
            <StatusBadge tone="neutral">Version {settings.version}</StatusBadge>
          </div>
          <form className="workflow-form" onSubmit={(event) => void saveGlobal(event)}>
            <div className="override-grid">
              <label>
                Default crawl profile
                <select
                  value={globalDraft.default_crawl_profile}
                  onChange={(event) => {
                    setGlobalDraft({ ...globalDraft, default_crawl_profile: event.target.value });
                    setDirty(true);
                  }}
                >
                  {['quick_audit', 'standard_crawl', 'deep_crawl', 'sitemap_only'].map((item) => (
                    <option key={item} value={item}>
                      {readable(item)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Default preset suggestion
                <select
                  value={globalDraft.default_platform_preset ?? ''}
                  onChange={(event) => {
                    setGlobalDraft({
                      ...globalDraft,
                      default_platform_preset: (event.target.value ||
                        null) as PlatformPresetId | null,
                    });
                    setDirty(true);
                  }}
                >
                  <option value="">No default suggestion</option>
                  {platformPresetIds.map((item) => (
                    <option key={item} value={item}>
                      {readable(item)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Default report page size
                <select
                  value={globalDraft.default_report_page_size}
                  onChange={(event) => {
                    setGlobalDraft({
                      ...globalDraft,
                      default_report_page_size: Number(event.target.value),
                    });
                    setDirty(true);
                  }}
                >
                  {[50, 100, 500].map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
              </label>
            </div>
            <fieldset>
              <legend>Default metadata thresholds</legend>
              <div className="override-grid">
                {thresholdFields.map(([key, label]) => (
                  <label key={key}>
                    {label}
                    <input
                      type="number"
                      min="1"
                      max={key.startsWith('title') ? 512 : 2048}
                      value={globalDraft.metadata_thresholds[key] ?? ''}
                      onChange={(event) => {
                        setGlobalDraft({
                          ...globalDraft,
                          metadata_thresholds: {
                            ...globalDraft.metadata_thresholds,
                            [key]: Number(event.target.value),
                          },
                        });
                        setDirty(true);
                      }}
                    />
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="option-grid">
              {(['images', 'structured_data'] as const).map((key) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={globalDraft.specialist_summaries[key] ?? false}
                    onChange={(event) => {
                      setGlobalDraft({
                        ...globalDraft,
                        specialist_summaries: {
                          ...globalDraft.specialist_summaries,
                          [key]: event.target.checked,
                        },
                      });
                      setDirty(true);
                    }}
                  />
                  Enable {readable(key)} specialist summary
                </label>
              ))}
            </div>
            <Alert>
              Pagination sitemap policy remains Review. Retention and export ceilings remain
              protected at {globalDraft.maximum_retained_urls.toLocaleString()} URLs and{' '}
              {globalDraft.maximum_export_rows.toLocaleString()} rows.
            </Alert>
            <label>
              Tracking parameters (comma separated)
              <input
                value={globalDraft.default_tracking_parameters.join(', ')}
                onChange={(event) => {
                  setGlobalDraft({
                    ...globalDraft,
                    default_tracking_parameters: event.target.value
                      .split(',')
                      .map((item) => item.trim())
                      .filter(Boolean),
                  });
                  setDirty(true);
                }}
              />
            </label>
            <label>
              Global URL rules (bounded JSON array)
              <textarea
                value={JSON.stringify(globalDraft.default_url_rules, null, 2)}
                onChange={(event) => {
                  try {
                    const rules = JSON.parse(event.target.value) as UrlRule[];
                    setGlobalDraft({ ...globalDraft, default_url_rules: rules });
                    setError(null);
                    setDirty(true);
                  } catch {
                    setError('Global URL rules must be a valid JSON array.');
                  }
                }}
                aria-describedby="global-rule-bound"
              />
              <small id="global-rule-bound">
                Maximum 500 rules; regex and wildcards are unsupported.
              </small>
            </label>
            <div className="toolbar">
              <Button type="submit" disabled={saving || !dirty}>
                Save global defaults
              </Button>
              <Button
                type="button"
                className="button--quiet"
                onClick={() => {
                  setGlobalDraft(settings.configuration);
                  setDirty(false);
                }}
              >
                Reset unsaved changes
              </Button>
            </div>
          </form>
        </Card>
      ) : null}

      <Card className="workflow-panel">
        <p className="eyebrow">Versioned configuration</p>
        <h2>Platform preset and saved profile</h2>
        <div className="override-grid">
          <label>
            Saved site profile
            <select
              value={selectedProfileId}
              onChange={(event) => {
                updateQuery('profile', event.target.value);
              }}
            >
              <option value="">Use global defaults</option>
              {profiles?.items
                .filter((item) => administrator || item.state === 'enabled')
                .map((item) => (
                  <option
                    key={item.profile_id}
                    value={item.profile_id}
                    disabled={item.state !== 'enabled'}
                  >
                    {item.site_label} — {item.seed_host} ({item.state})
                  </option>
                ))}
            </select>
          </label>
          <label>
            Platform preset
            <select
              value={selectedPresetId}
              onChange={(event) => {
                updateQuery('preset', event.target.value);
              }}
            >
              <option value="">Select a preset</option>
              {presets.map((item) => (
                <option key={item.preset_id} value={item.preset_id}>
                  {item.label} — {item.version}
                </option>
              ))}
            </select>
          </label>
        </div>
        {selectedPreset ? (
          <div className="preset-review">
            <p>{selectedPreset.explanation}</p>
            {selectedPreset.preset_id === 'wordpress' ? (
              <Alert>
                Tag, author, and date archives default to metadata and sitemap exclusion through
                independent rules. Pagination remains metadata-scoring eligible and its sitemap
                policy is Review. Categories are not excluded automatically.
              </Alert>
            ) : null}
            <label className="check-control">
              <input
                type="checkbox"
                checked={accepted}
                onChange={(event) => {
                  setAccepted(event.target.checked);
                  if (!event.target.checked) setTrackingAccepted(false);
                }}
              />
              Explicitly accept {selectedPreset.label} {selectedPreset.version} for this preview
            </label>
            <label className="check-control">
              <input
                type="checkbox"
                checked={trackingAccepted}
                disabled={!accepted || !selectedPreset.tracking_parameters.length}
                onChange={(event) => {
                  setTrackingAccepted(event.target.checked);
                }}
              />
              Strip the exact reviewed tracking-parameter list
            </label>
            <p className="code-list">
              {selectedPreset.tracking_parameters.join(', ') || 'No preset tracking parameters'}
            </p>
            <div className="rule-list" aria-label="Preset rules">
              {selectedPreset.rules.map((item) => (
                <label className="check-control" key={item.rule_id}>
                  <input
                    type="checkbox"
                    checked={ruleStates[item.rule_id] ?? item.enabled}
                    disabled={!accepted}
                    onChange={(event) => {
                      setRuleStates({ ...ruleStates, [item.rule_id]: event.target.checked });
                    }}
                  />
                  <span>
                    <strong>{item.name}</strong>{' '}
                    <small>
                      {readable(item.action)} · {item.match_value} ·{' '}
                      {item.enabled ? 'default on' : 'optional'}
                    </small>
                  </span>
                </label>
              ))}
            </div>
            <label>
              Functional parameter exceptions (comma separated)
              <input
                value={trackingExceptions}
                onChange={(event) => {
                  setTrackingExceptions(event.target.value);
                }}
              />
            </label>
          </div>
        ) : null}
      </Card>

      <Card className="workflow-panel">
        <p className="eyebrow">Stateless preview</p>
        <h2>URL rule tester</h2>
        <p>
          Seven literal string match types and five actions are supported. This operation performs
          no network access.
        </p>
        <div className="override-grid">
          <label>
            Rule name
            <input
              value={rule.name}
              onChange={(event) => {
                setRule({ ...rule, name: event.target.value });
              }}
            />
          </label>
          <label>
            Match type
            <select
              value={rule.match_type}
              onChange={(event) => {
                setRule({ ...rule, match_type: event.target.value as RuleMatchType });
              }}
            >
              {ruleMatchTypes.map((item) => (
                <option key={item} value={item}>
                  {readable(item)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Match value
            <input
              value={rule.match_value}
              maxLength={2048}
              onChange={(event) => {
                setRule({ ...rule, match_value: event.target.value });
              }}
            />
          </label>
          <label>
            Action
            <select
              value={rule.action}
              onChange={(event) => {
                setRule({ ...rule, action: event.target.value as RuleAction });
              }}
            >
              {ruleActions.map((item) => (
                <option key={item} value={item}>
                  {readable(item)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Human-readable reason
            <input
              value={rule.reason}
              onChange={(event) => {
                setRule({ ...rule, reason: event.target.value });
              }}
            />
          </label>
          <label className="check-control">
            <input
              type="checkbox"
              checked={rule.case_sensitive}
              onChange={(event) => {
                setRule({ ...rule, case_sensitive: event.target.checked });
              }}
            />
            Case-sensitive path or query comparison
          </label>
        </div>
        {rule.match_type === 'path_contains' && rule.match_value.length < 3 ? (
          <Alert tone="warning">
            This is a broad path-contains rule and requires careful review.
          </Alert>
        ) : null}
        <label className="sample-urls">
          Sample URLs, one per line (maximum 100)
          <textarea
            value={samples}
            onChange={(event) => {
              setSamples(event.target.value);
            }}
          />
        </label>
        <label className="sample-urls">
          Disabled inherited rule IDs (comma separated)
          <input
            value={disabledRuleIds}
            onChange={(event) => {
              setDisabledRuleIds(event.target.value);
            }}
            placeholder="global.rule_id, wordpress.optional_rule"
          />
        </label>
        <div className="toolbar">
          <Button type="button" onClick={() => void preview()}>
            Resolve effective settings
          </Button>
          <Button type="button" onClick={() => void testRules()}>
            Test sample URLs
          </Button>
          <Button
            type="button"
            className="button--quiet"
            onClick={() => {
              setRule(emptyRule());
              setSamples('https://example.com/private/page\nhttps://example.com/');
              setEffective(null);
              setTestResult(null);
              setDisabledRuleIds('');
            }}
          >
            Reset temporary overrides
          </Button>
        </div>
      </Card>

      {effective ? <EffectiveSettingsView value={effective} /> : null}
      {testResult ? <RuleTestView value={testResult} /> : null}

      {administrator ? (
        <Card className="workflow-panel">
          <p className="eyebrow">Administrator</p>
          <h2>Saved site profiles</h2>
          <TableFoundation>
            <thead>
              <tr>
                <th>Site</th>
                <th>Seed</th>
                <th>Preset</th>
                <th>State</th>
                <th>Version</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {!profiles?.items.length ? (
                <tr>
                  <td colSpan={6}>No saved site profiles are available.</td>
                </tr>
              ) : null}
              {profiles?.items.map((item) => (
                <tr key={item.profile_id}>
                  <td>
                    {item.site_label}
                    <small className="secondary-id">{item.profile_id}</small>
                  </td>
                  <td>{item.authorized_seed}</td>
                  <td>{item.configuration.preset_id ?? 'None'}</td>
                  <td>{item.state}</td>
                  <td>{item.current_version}</td>
                  <td>
                    <div className="toolbar">
                      <Button
                        type="button"
                        onClick={() => {
                          setEditingProfile(item);
                          setProfileDraft(item.configuration);
                        }}
                      >
                        Edit
                      </Button>
                      {item.state === 'enabled' ? (
                        <Button
                          type="button"
                          className="button--quiet"
                          onClick={() => void profileState(item, 'disable')}
                        >
                          Disable
                        </Button>
                      ) : null}
                      {item.state !== 'archived' ? (
                        <Button
                          type="button"
                          className="button--quiet"
                          onClick={() => void profileState(item, 'archive')}
                        >
                          Archive
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </TableFoundation>
          <form
            className="workflow-form profile-editor"
            onSubmit={(event) => void saveProfile(event)}
          >
            <h3>{editingProfile ? `Edit ${editingProfile.site_label}` : 'Create site profile'}</h3>
            <div className="override-grid">
              <label>
                Site label
                <input
                  required
                  maxLength={200}
                  value={profileDraft.site_label}
                  onChange={(event) => {
                    setProfileDraft({ ...profileDraft, site_label: event.target.value });
                    setDirty(true);
                  }}
                />
              </label>
              <label>
                Authorized seed
                <input
                  required
                  type="url"
                  value={profileDraft.authorized_seed}
                  onChange={(event) => {
                    setProfileDraft({ ...profileDraft, authorized_seed: event.target.value });
                    setDirty(true);
                  }}
                />
              </label>
              <label>
                Approved hosts (comma separated)
                <input
                  required
                  value={profileDraft.approved_hosts.join(', ')}
                  onChange={(event) => {
                    setProfileDraft({
                      ...profileDraft,
                      approved_hosts: event.target.value
                        .split(',')
                        .map((item) => item.trim())
                        .filter(Boolean),
                    });
                    setDirty(true);
                  }}
                />
              </label>
              <label>
                Crawl profile
                <select
                  value={profileDraft.crawl_profile}
                  onChange={(event) => {
                    setProfileDraft({ ...profileDraft, crawl_profile: event.target.value });
                    setDirty(true);
                  }}
                >
                  {['quick_audit', 'standard_crawl', 'deep_crawl', 'sitemap_only'].map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
              </label>
              <label>
                Accepted preset
                <select
                  value={profileDraft.preset_id ?? ''}
                  onChange={(event) => {
                    const presetId = (event.target.value || null) as PlatformPresetId | null;
                    const preset = presets.find((item) => item.preset_id === presetId);
                    setProfileDraft({
                      ...profileDraft,
                      preset_id: presetId,
                      preset_version: preset?.version ?? null,
                      preset_accepted: Boolean(preset),
                      tracking_parameters_accepted: false,
                      preset_rule_states: {},
                    });
                    setDirty(true);
                  }}
                >
                  <option value="">No preset</option>
                  {presets.map((item) => (
                    <option key={item.preset_id} value={item.preset_id}>
                      {item.label} — {item.version}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Parameter exceptions
                <input
                  value={profileDraft.tracking_parameter_exceptions.join(', ')}
                  onChange={(event) => {
                    setProfileDraft({
                      ...profileDraft,
                      tracking_parameter_exceptions: event.target.value
                        .split(',')
                        .map((item) => item.trim())
                        .filter(Boolean),
                    });
                    setDirty(true);
                  }}
                />
              </label>
            </div>
            <label className="check-control">
              <input
                type="checkbox"
                disabled={!profileDraft.preset_accepted}
                checked={profileDraft.tracking_parameters_accepted}
                onChange={(event) => {
                  setProfileDraft({
                    ...profileDraft,
                    tracking_parameters_accepted: event.target.checked,
                  });
                  setDirty(true);
                }}
              />
              Accept preset tracking-parameter stripping
            </label>
            {profilePreset ? (
              <fieldset>
                <legend>Saved preset rule states</legend>
                <div className="rule-list">
                  {profilePreset.rules.map((item) => (
                    <label className="check-control" key={item.rule_id}>
                      <input
                        type="checkbox"
                        checked={profileDraft.preset_rule_states[item.rule_id] ?? item.enabled}
                        onChange={(event) => {
                          setProfileDraft({
                            ...profileDraft,
                            preset_rule_states: {
                              ...profileDraft.preset_rule_states,
                              [item.rule_id]: event.target.checked,
                            },
                          });
                          setDirty(true);
                        }}
                      />
                      <span>
                        <strong>{item.name}</strong>
                        <small>
                          {item.match_value} · {item.enabled ? 'default on' : 'optional'}
                        </small>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ) : null}
            <label>
              Site-specific URL rules (bounded JSON array)
              <textarea
                value={JSON.stringify(profileDraft.rules, null, 2)}
                onChange={(event) => {
                  try {
                    setProfileDraft({
                      ...profileDraft,
                      rules: JSON.parse(event.target.value) as UrlRule[],
                    });
                    setError(null);
                    setDirty(true);
                  } catch {
                    setError('Site-profile rules must be a valid JSON array.');
                  }
                }}
              />
            </label>
            <label>
              Crawl limit overrides (bounded JSON object)
              <textarea
                value={JSON.stringify(profileDraft.crawl_limit_overrides, null, 2)}
                onChange={(event) => {
                  try {
                    setProfileDraft({
                      ...profileDraft,
                      crawl_limit_overrides: JSON.parse(event.target.value) as Record<
                        string,
                        number
                      >,
                    });
                    setError(null);
                    setDirty(true);
                  } catch {
                    setError('Crawl limit overrides must be a valid JSON object.');
                  }
                }}
              />
            </label>
            <label>
              Metadata threshold overrides (bounded JSON object)
              <textarea
                value={JSON.stringify(profileDraft.metadata_thresholds, null, 2)}
                onChange={(event) => {
                  try {
                    setProfileDraft({
                      ...profileDraft,
                      metadata_thresholds: JSON.parse(event.target.value) as Record<string, number>,
                    });
                    setError(null);
                    setDirty(true);
                  } catch {
                    setError('Metadata thresholds must be a valid JSON object.');
                  }
                }}
              />
            </label>
            <label>
              Business-importance assignments (bounded JSON array)
              <textarea
                value={JSON.stringify(profileDraft.business_importance, null, 2)}
                onChange={(event) => {
                  try {
                    setProfileDraft({
                      ...profileDraft,
                      business_importance: JSON.parse(event.target.value) as Record<
                        string,
                        string
                      >[],
                    });
                    setError(null);
                    setDirty(true);
                  } catch {
                    setError('Business-importance assignments must be a valid JSON array.');
                  }
                }}
              />
            </label>
            <div className="option-grid">
              {(['images', 'structured_data'] as const).map((key) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={profileDraft.enabled_modules[key] ?? false}
                    onChange={(event) => {
                      setProfileDraft({
                        ...profileDraft,
                        enabled_modules: {
                          ...profileDraft.enabled_modules,
                          [key]: event.target.checked,
                        },
                      });
                      setDirty(true);
                    }}
                  />
                  Enable {readable(key)} summary
                </label>
              ))}
            </div>
            <div className="toolbar">
              <Button type="submit" disabled={saving}>
                {editingProfile ? 'Save new profile version' : 'Create profile'}
              </Button>
              <Button
                type="button"
                className="button--quiet"
                onClick={() => {
                  setEditingProfile(null);
                  setProfileDraft(emptyProfile());
                  setDirty(false);
                }}
              >
                Clear editor
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
    </>
  );
}

function EffectiveSettingsView({ value }: { value: EffectiveSettings }) {
  const crawlLimits = stringRecord(value.crawl_limit_overrides);
  const thresholds = stringRecord(value.metadata_thresholds);
  return (
    <Card className="workflow-panel" aria-live="polite">
      <p className="eyebrow">Resolved result</p>
      <h2>Effective settings</h2>
      <div className="metric-grid">
        <div>
          <span>Preset</span>
          <strong>{value.preset ? `${value.preset.label} ${value.preset.version}` : 'None'}</strong>
          <small>{value.preset_accepted ? 'Explicitly accepted' : 'Not accepted'}</small>
        </div>
        <div>
          <span>Site profile</span>
          <strong>{value.site_profile?.site_label ?? 'Global defaults'}</strong>
          <small>
            {value.site_profile
              ? `Version ${String(value.site_profile.version)}`
              : 'No saved profile selected'}
          </small>
        </div>
        <div>
          <span>Effective rules</span>
          <strong>{value.effective_rules.length}</strong>
          <small>{value.disabled_inherited_rules.length} inherited rules disabled</small>
        </div>
      </div>
      {value.warnings.length ? (
        <Alert tone="warning">{value.warnings.map(readable).join(', ')}</Alert>
      ) : null}
      <dl className="settings-breakdown">
        <div>
          <dt>Crawl limits</dt>
          <dd>{JSON.stringify(crawlLimits)}</dd>
        </div>
        <div>
          <dt>Metadata thresholds</dt>
          <dd>{JSON.stringify(thresholds)}</dd>
        </div>
        <div>
          <dt>Tracking parameters</dt>
          <dd>
            {value.tracking_parameters_accepted
              ? value.tracking_parameters.join(', ')
              : 'Not accepted'}
          </dd>
        </div>
        <div>
          <dt>Protected boundaries</dt>
          <dd>
            SSRF, DNS, redirect, authorization, approved-host scope, and hard maxima remain
            enforced.
          </dd>
        </div>
      </dl>
      <TableFoundation>
        <thead>
          <tr>
            <th>Rule</th>
            <th>Source</th>
            <th>Match</th>
            <th>Action</th>
            <th>State</th>
          </tr>
        </thead>
        <tbody>
          {value.effective_rules.map((item) => (
            <tr key={`${item.source ?? 'source'}-${item.rule_id}`}>
              <td>
                {item.name}
                <small className="secondary-id">{item.rule_id}</small>
              </td>
              <td>{readable(item.source ?? 'unknown')}</td>
              <td>
                {readable(item.match_type)}: {item.match_value}
              </td>
              <td>{readable(item.action)}</td>
              <td>Enabled</td>
            </tr>
          ))}
        </tbody>
      </TableFoundation>
    </Card>
  );
}

function RuleTestView({ value }: { value: RuleTestResult }) {
  return (
    <Card className="workflow-panel" aria-live="polite">
      <p className="eyebrow">Read-only result</p>
      <h2>Sample URL matches</h2>
      <p>{value.test.result_count} samples · network access: no · discoveries created: no</p>
      <TableFoundation>
        <thead>
          <tr>
            <th>Original URL</th>
            <th>Normalized URL</th>
            <th>Matched</th>
            <th>Primary rule</th>
            <th>Conflict</th>
          </tr>
        </thead>
        <tbody>
          {value.test.results.map((item, index) => (
            <tr key={`${textValue(item.original_url)}-${String(index)}`}>
              <td>{textValue(item.original_url)}</td>
              <td>{textValue(item.normalized_url)}</td>
              <td>{item.matched ? 'Yes' : 'No'}</td>
              <td>{textValue(item.primary_rule) || 'None'}</td>
              <td>{item.conflict ? 'Review required' : 'No'}</td>
            </tr>
          ))}
        </tbody>
      </TableFoundation>
    </Card>
  );
}
