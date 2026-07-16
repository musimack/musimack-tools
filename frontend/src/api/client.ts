import { environment } from '../config/environment';
import { permissions, roles, type Permission, type Principal, type Role } from '../auth/contracts';

export const FRONTEND_API_CLIENT_VERSION = 'seo-toolkit-frontend-api-client-v1' as const;

type JsonRecord = Record<string, unknown>;
export type ApiErrorDetail = { code: string; message: string; field?: string };
export type CorrelationMetadata = { correlationId: string | null };
export type ApiSuccessEnvelope<T> = CorrelationMetadata & { data: T; status: number };
export type ApiErrorEnvelope = {
  request_id?: string | null;
  error: { code: string; message: string; details: readonly ApiErrorDetail[] };
};
export type SignInRequest = { email: string; password: string };
export type SignInResponse = { principal: Principal };
export type SignOutResponse = { signedOut: boolean };
export type HealthResponse = { application: string; status: 'healthy' };
export type SafeDiagnosticsSummary = {
  frontendVersion: string;
  apiClientVersion: string;
  apiBaseMode: 'same-origin' | 'local-development';
  requestTimeoutMs: number;
};
export type ApiRequestInit = RequestInit & { timeoutMs?: number };

const correlationIdPattern = /^[A-Za-z0-9._:-]{1,128}$/u;
let authenticationFailureHandler: (() => void) | null = null;

export function registerAuthenticationFailureHandler(handler: () => void): () => void {
  authenticationFailureHandler = handler;
  return () => {
    if (authenticationFailureHandler === handler) authenticationFailureHandler = null;
  };
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null,
    readonly details: readonly ApiErrorDetail[],
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function safeCorrelationId(value: unknown): string | null {
  return typeof value === 'string' && correlationIdPattern.test(value) ? value : null;
}

function isRole(value: unknown): value is Role {
  return typeof value === 'string' && (roles as readonly string[]).includes(value);
}

function isPermission(value: unknown): value is Permission {
  return typeof value === 'string' && (permissions as readonly string[]).includes(value);
}

export function parsePrincipal(value: unknown): Principal {
  if (!isRecord(value) || !isRole(value.role) || !Array.isArray(value.permissions)) {
    throw new ApiError(
      502,
      'invalid_response',
      'The service returned an invalid identity response.',
      null,
      [],
    );
  }
  const parsedPermissions = value.permissions.filter(isPermission);
  if (parsedPermissions.length !== value.permissions.length) {
    throw new ApiError(
      502,
      'invalid_response',
      'The service returned an unknown permission.',
      null,
      [],
    );
  }
  const requiredStrings = [
    'authentication_method',
    'authentication_version',
    'authorization_version',
    'session_version',
  ] as const;
  if (
    requiredStrings.some((key) => typeof value[key] !== 'string') ||
    typeof value.password_change_available !== 'boolean'
  ) {
    throw new ApiError(
      502,
      'invalid_response',
      'The service returned an incomplete identity response.',
      null,
      [],
    );
  }
  return {
    userId: optionalString(value.user_id),
    email: optionalString(value.email),
    displayName: optionalString(value.display_name),
    role: value.role,
    permissions: parsedPermissions,
    authenticationMethod: value.authentication_method as string,
    sessionCreatedAt: optionalString(value.session_created_at),
    sessionExpiresAt: optionalString(value.session_expires_at),
    sessionAbsoluteExpiresAt: optionalString(value.session_absolute_expires_at),
    passwordChangeAvailable: value.password_change_available,
    authenticationVersion: value.authentication_version as string,
    authorizationVersion: value.authorization_version as string,
    sessionVersion: value.session_version as string,
  };
}

async function responseBody(response: Response): Promise<{ body: unknown; isJson: boolean }> {
  if (response.status === 204 || response.headers.get('content-length') === '0')
    return { body: null, isJson: true };
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('application/json')) return { body: null, isJson: false };
  try {
    return { body: (await response.json()) as unknown, isJson: true };
  } catch {
    return { body: null, isJson: false };
  }
}

function errorFrom(response: Response, body: unknown): ApiError {
  const headerId = safeCorrelationId(response.headers.get('x-request-id'));
  if (isRecord(body) && isRecord(body.error)) {
    const details = Array.isArray(body.error.details)
      ? body.error.details.filter(isRecord).map((item) => ({
          code: typeof item.code === 'string' ? item.code : 'unknown',
          message: typeof item.message === 'string' ? item.message : 'The request failed.',
          ...(typeof item.field === 'string' ? { field: item.field } : {}),
        }))
      : [];
    return new ApiError(
      response.status,
      typeof body.error.code === 'string' ? body.error.code : 'request_failed',
      typeof body.error.message === 'string' ? body.error.message : 'The request failed.',
      safeCorrelationId(body.request_id) ?? headerId,
      details,
    );
  }
  return new ApiError(
    response.status,
    'request_failed',
    'The service could not complete the request.',
    headerId,
    [],
  );
}

function assertRelativePath(path: string): void {
  if (!path.startsWith('/') || path.startsWith('//') || /[\r\n]/u.test(path)) {
    throw new ApiError(0, 'invalid_request_path', 'The API request path is invalid.', null, []);
  }
}

export async function request(
  path: string,
  init: ApiRequestInit = {},
): Promise<ApiSuccessEnvelope<unknown>> {
  assertRelativePath(path);
  const { timeoutMs = environment.requestTimeoutMs, signal, ...requestInit } = init;
  const controller = new AbortController();
  const timeoutReason = Symbol('request-timeout');
  const abortFromCaller = () => {
    controller.abort();
  };
  signal?.addEventListener('abort', abortFromCaller, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = window.setTimeout(() => {
    controller.abort(timeoutReason);
  }, timeoutMs);
  let response: Response;
  try {
    const headers = new Headers(requestInit.headers);
    headers.set('Accept', 'application/json');
    if (requestInit.body) headers.set('Content-Type', 'application/json');
    response = await fetch(`${environment.apiBaseUrl}${path}`, {
      ...requestInit,
      credentials: 'include',
      headers,
      signal: controller.signal,
    });
  } catch {
    const timeoutFailure = controller.signal.reason === timeoutReason;
    const code = timeoutFailure
      ? 'request_timeout'
      : signal?.aborted
        ? 'request_cancelled'
        : 'service_unavailable';
    const message = timeoutFailure
      ? 'The service request timed out.'
      : signal?.aborted
        ? 'The service request was cancelled.'
        : 'The service is unavailable.';
    throw new ApiError(0, code, message, null, []);
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener('abort', abortFromCaller);
  }
  const parsed = await responseBody(response);
  if (!response.ok) {
    if (response.status === 401) authenticationFailureHandler?.();
    throw errorFrom(response, parsed.body);
  }
  if (!parsed.isJson)
    throw new ApiError(
      response.status,
      'unexpected_content_type',
      'The service returned an unexpected response.',
      safeCorrelationId(response.headers.get('x-request-id')),
      [],
    );
  return {
    data: parsed.body,
    status: response.status,
    correlationId: safeCorrelationId(response.headers.get('x-request-id')),
  };
}

export async function requestJson(path: string, init: ApiRequestInit = {}): Promise<unknown> {
  return (await request(path, init)).data;
}

export const authApi = {
  async me(): Promise<Principal> {
    return parsePrincipal(await requestJson('/auth/me'));
  },
  async signIn(email: string, password: string): Promise<Principal> {
    const payload: SignInRequest = { email, password };
    const body = await requestJson('/auth/sign-in', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    if (!isRecord(body))
      throw new ApiError(
        502,
        'invalid_response',
        'The service returned an invalid sign-in response.',
        null,
        [],
      );
    return parsePrincipal(body.principal);
  },
  async signOut(): Promise<void> {
    await requestJson('/auth/sign-out', { method: 'POST' });
  },
};
