import type { Permission } from '../auth/contracts';

export const viewerPermissions: readonly Permission[] = [
  'jobs.view',
  'runs.view',
  'history.view',
  'artifacts.view',
  'artifacts.download',
  'diagnostics.view',
  'sessions.view_own',
  'sessions.revoke_own',
  'password.change_own',
  'settings.view',
];

export function principalJson(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    user_id: 'user-1',
    email: 'viewer@example.test',
    display_name: 'River Stone',
    role: 'viewer',
    permissions: viewerPermissions,
    authentication_method: 'password_session',
    session_created_at: '2026-07-16T10:00:00Z',
    session_expires_at: '2026-07-16T11:00:00Z',
    session_absolute_expires_at: '2026-07-17T10:00:00Z',
    password_change_available: true,
    authentication_version: 'seo-toolkit-authentication-v1',
    authorization_version: 'seo-toolkit-authorization-v1',
    session_version: 'seo-toolkit-session-v1',
    ...overrides,
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
