import { jsonResponse } from '../test/fixtures';
import { siteAuditSettingsApi } from './api';

describe('site-audit settings API', () => {
  test('uses private same-origin endpoints and bounded profile pagination', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        data: { items: [], offset: 0, limit: 500, total: 0, ordering: 'stable' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await siteAuditSettingsApi.profiles(false);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/site-audits/site-profiles?offset=0&limit=500&include_disabled=false',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  test('uses the same explicit governance request for effective settings and tests', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(() => Promise.resolve(jsonResponse({ data: {} })));
    vi.stubGlobal('fetch', fetchMock);
    const request = {
      preset_id: 'wordpress' as const,
      preset_version: 'wordpress-1',
      preset_accepted: true,
      sample_urls: ['https://example.com/a'],
      overrides: { rules: [] },
    };
    await siteAuditSettingsApi.effectiveSettings(request);
    await siteAuditSettingsApi.testRules(request);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/internal/v1/site-audits/effective-settings',
      '/api/internal/v1/site-audits/rule-tests',
    ]);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify(request),
    });
  });

  test('serializes versioned administrator mutations and rejects unsafe identifiers', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ data: { profile_id: 'profile-1', current_version: 2 } }));
    vi.stubGlobal('fetch', fetchMock);
    await siteAuditSettingsApi.updateProfile('profile-1', { site_label: 'Example' } as never, 1);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/site-audits/site-profiles/profile-1',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          expected_version: 1,
          configuration: { site_label: 'Example' },
        }),
      }),
    );
    await expect(siteAuditSettingsApi.profile('../unsafe')).rejects.toMatchObject({
      code: 'invalid_identifier',
    });
  });
});
