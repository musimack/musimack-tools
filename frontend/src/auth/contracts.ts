export const FRONTEND_AUTH_VERSION = 'seo-toolkit-frontend-auth-v1' as const;

export const roles = ['administrator', 'operator', 'viewer'] as const;
export type Role = (typeof roles)[number];

export const permissions = [
  'jobs.submit',
  'jobs.cancel',
  'jobs.view',
  'runs.view',
  'history.view',
  'artifacts.view',
  'artifacts.download',
  'diagnostics.view',
  'diagnostics.view_sensitive',
  'users.view',
  'users.create',
  'users.update',
  'users.activate',
  'users.deactivate',
  'users.change_role',
  'sessions.view_own',
  'sessions.revoke_own',
  'sessions.revoke_any',
  'password.change_own',
  'password.reset_other',
  'auth_audit.view',
  'settings.view',
  'settings.manage',
] as const;
export type Permission = (typeof permissions)[number];

export type Principal = {
  userId: string | null;
  email: string | null;
  displayName: string | null;
  role: Role;
  permissions: readonly Permission[];
  authenticationMethod: string;
  sessionCreatedAt: string | null;
  sessionExpiresAt: string | null;
  sessionAbsoluteExpiresAt: string | null;
  passwordChangeAvailable: boolean;
  authenticationVersion: string;
  authorizationVersion: string;
  sessionVersion: string;
};

export type AuthStatus =
  'initializing' | 'authenticated' | 'unauthenticated' | 'expired' | 'unavailable';
