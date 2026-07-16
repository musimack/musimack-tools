export const FRONTEND_FOUNDATION_VERSION = 'seo-toolkit-frontend-foundation-v1' as const;

const defaultApiBaseUrl = '/api/internal/v1';
const defaultRequestTimeoutMs = 10_000;
const minimumRequestTimeoutMs = 1_000;
const maximumRequestTimeoutMs = 30_000;

export type FrontendEnvironment = {
  apiBaseUrl: string;
  appName: string;
  frontendVersion: typeof FRONTEND_FOUNDATION_VERSION;
  requestTimeoutMs: number;
  developmentDiagnostics: boolean;
  apiBaseMode: 'same-origin' | 'local-development';
};
export type FrontendEnvironmentValues = Pick<
  ImportMetaEnv,
  | 'VITE_API_BASE_URL'
  | 'VITE_APP_NAME'
  | 'VITE_FRONTEND_VERSION'
  | 'VITE_REQUEST_TIMEOUT_MS'
  | 'VITE_ENABLE_DEV_DIAGNOSTICS'
>;

function optionalValue(value: string | undefined): string | undefined {
  const configured = value?.trim();
  return configured === undefined || configured.length === 0 ? undefined : configured;
}

export function apiBaseUrl(value = import.meta.env.VITE_API_BASE_URL): string {
  const candidate = optionalValue(value) ?? defaultApiBaseUrl;
  if (
    !candidate.startsWith('/') &&
    !candidate.startsWith('http://127.0.0.1:') &&
    !candidate.startsWith('http://localhost:')
  ) {
    throw new Error('VITE_API_BASE_URL must be relative or target the local development host.');
  }
  return candidate.replace(/\/$/, '');
}

function parseVersion(value: string | undefined): typeof FRONTEND_FOUNDATION_VERSION {
  const configured = optionalValue(value) ?? FRONTEND_FOUNDATION_VERSION;
  if (configured !== FRONTEND_FOUNDATION_VERSION) {
    throw new Error('VITE_FRONTEND_VERSION is unsupported.');
  }
  return configured;
}

function parseTimeout(value: string | undefined): number {
  const configured = optionalValue(value);
  if (configured === undefined) return defaultRequestTimeoutMs;
  const parsed = Number(configured);
  if (
    !Number.isInteger(parsed) ||
    parsed < minimumRequestTimeoutMs ||
    parsed > maximumRequestTimeoutMs
  ) {
    throw new Error('VITE_REQUEST_TIMEOUT_MS must be an integer from 1000 through 30000.');
  }
  return parsed;
}

function parseBoolean(value: string | undefined): boolean {
  const configured = optionalValue(value);
  if (configured === undefined || configured === 'false') return false;
  if (configured === 'true') return true;
  throw new Error('VITE_ENABLE_DEV_DIAGNOSTICS must be true or false.');
}

export function readEnvironment(
  values: FrontendEnvironmentValues = import.meta.env,
): FrontendEnvironment {
  const baseUrl = apiBaseUrl(values.VITE_API_BASE_URL);
  const appName = optionalValue(values.VITE_APP_NAME) ?? 'Musimack SEO Toolkit';
  if (appName.length > 80 || /[<>]/u.test(appName)) throw new Error('VITE_APP_NAME is invalid.');
  const requestedDiagnostics = parseBoolean(values.VITE_ENABLE_DEV_DIAGNOSTICS);
  return {
    apiBaseUrl: baseUrl,
    appName,
    frontendVersion: parseVersion(values.VITE_FRONTEND_VERSION),
    requestTimeoutMs: parseTimeout(values.VITE_REQUEST_TIMEOUT_MS),
    developmentDiagnostics: import.meta.env.DEV && requestedDiagnostics,
    apiBaseMode: baseUrl.startsWith('/') ? 'same-origin' : 'local-development',
  };
}

export const environment = readEnvironment();
