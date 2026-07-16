import { apiBaseUrl, readEnvironment, type FrontendEnvironmentValues } from './environment';

function values(overrides: Partial<FrontendEnvironmentValues> = {}): FrontendEnvironmentValues {
  return { ...overrides };
}

describe('frontend environment', () => {
  test.each([undefined, '', '   '])('uses the internal API default for %p', (value) => {
    expect(apiBaseUrl(value)).toBe('/api/internal/v1');
  });

  test('removes one trailing slash', () => {
    expect(apiBaseUrl('/api/internal/v1/')).toBe('/api/internal/v1');
  });

  test.each(['https://public.example/api', 'http://192.0.2.10:8000/api'])(
    'rejects unsafe development API target %s',
    (value) => {
      expect(() => apiBaseUrl(value)).toThrow('local development host');
    },
  );

  test('parses the exact supported environment contract', () => {
    expect(readEnvironment(values({ VITE_REQUEST_TIMEOUT_MS: '12000' }))).toMatchObject({
      frontendVersion: 'seo-toolkit-frontend-foundation-v1',
      requestTimeoutMs: 12000,
      apiBaseMode: 'same-origin',
    });
  });

  test.each([
    [{ VITE_FRONTEND_VERSION: 'frontend-v2' }, 'unsupported'],
    [{ VITE_REQUEST_TIMEOUT_MS: '999' }, '1000 through 30000'],
    [{ VITE_ENABLE_DEV_DIAGNOSTICS: 'yes' }, 'true or false'],
    [{ VITE_APP_NAME: '<script>' }, 'invalid'],
  ] satisfies readonly [Partial<FrontendEnvironmentValues>, string][])(
    'rejects malformed environment values %#',
    (override, message) => {
      expect(() => readEnvironment(values(override))).toThrow(message);
    },
  );
});
