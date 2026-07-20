import { ApiError, requestJson } from '../api/client';
import type {
  EffectiveSettings,
  GlobalConfiguration,
  GlobalSettings,
  GovernanceRequest,
  Preset,
  ProfilePage,
  RuleTestResult,
  SiteProfile,
  SiteProfileConfiguration,
  UrlRule,
} from './contracts';

const BASE = '/site-audits';
const record = (value: unknown): Record<string, unknown> => {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ApiError(502, 'invalid_response', 'The site-audit response is invalid.', null, []);
  return value as Record<string, unknown>;
};
const data = (value: unknown): unknown => record(value).data;
const identifier = (value: string): string => {
  if (!/^[A-Za-z0-9._-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The identifier is invalid.', null, []);
  return encodeURIComponent(value);
};
const post = async (path: string, body: unknown): Promise<unknown> =>
  data(await requestJson(path, { method: 'POST', body: JSON.stringify(body) }));

export const siteAuditSettingsApi = {
  settings: async () => data(await requestJson(`${BASE}/settings`)) as GlobalSettings,
  updateSettings: async (configuration: GlobalConfiguration, expectedVersion: number) =>
    data(
      await requestJson(`${BASE}/settings`, {
        method: 'PUT',
        body: JSON.stringify({ expected_version: expectedVersion, configuration }),
      }),
    ) as GlobalSettings,
  presets: async () => data(await requestJson(`${BASE}/presets`)) as Preset[],
  preset: async (presetId: string, version?: string) => {
    const query = version ? `?version=${encodeURIComponent(version)}` : '';
    return data(await requestJson(`${BASE}/presets/${identifier(presetId)}${query}`)) as Preset;
  },
  profiles: async (includeDisabled = false) =>
    data(
      await requestJson(
        `${BASE}/site-profiles?offset=0&limit=500&include_disabled=${String(includeDisabled)}`,
      ),
    ) as ProfilePage,
  profile: async (profileId: string) =>
    data(await requestJson(`${BASE}/site-profiles/${identifier(profileId)}`)) as SiteProfile,
  profileVersions: async (profileId: string) =>
    data(await requestJson(`${BASE}/site-profiles/${identifier(profileId)}/versions`)) as Record<
      string,
      unknown
    >[],
  createProfile: async (configuration: SiteProfileConfiguration) =>
    (await post(`${BASE}/site-profiles`, { configuration })) as SiteProfile,
  updateProfile: async (
    profileId: string,
    configuration: SiteProfileConfiguration,
    expectedVersion: number,
  ) =>
    data(
      await requestJson(`${BASE}/site-profiles/${identifier(profileId)}`, {
        method: 'PUT',
        body: JSON.stringify({ expected_version: expectedVersion, configuration }),
      }),
    ) as SiteProfile,
  disableProfile: async (profileId: string) =>
    (await post(`${BASE}/site-profiles/${identifier(profileId)}/disable`, {})) as SiteProfile,
  archiveProfile: async (profileId: string) =>
    (await post(`${BASE}/site-profiles/${identifier(profileId)}/archive`, {})) as SiteProfile,
  validateRule: async (rule: UrlRule) =>
    (await post(`${BASE}/rules/validate`, { rule })) as { valid: true; rule: UrlRule },
  effectiveSettings: async (request: GovernanceRequest) =>
    (await post(`${BASE}/effective-settings`, request)) as EffectiveSettings,
  testRules: async (request: GovernanceRequest) =>
    (await post(`${BASE}/rule-tests`, request)) as RuleTestResult,
  previewRules: async () => post(`${BASE}/rule-previews`, {}),
};
