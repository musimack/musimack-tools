import { FRONTEND_API_CLIENT_VERSION, type SafeDiagnosticsSummary } from '../api/client';
import { FRONTEND_AUTH_VERSION } from '../auth/contracts';
import { FRONTEND_DESIGN_SYSTEM_VERSION } from '../design-system/components';
import { environment } from './environment';

export const frontendDiagnostics: Readonly<
  SafeDiagnosticsSummary & {
    authVersion: string;
    designSystemVersion: string;
  }
> = Object.freeze({
  frontendVersion: environment.frontendVersion,
  apiClientVersion: FRONTEND_API_CLIENT_VERSION,
  authVersion: FRONTEND_AUTH_VERSION,
  designSystemVersion: FRONTEND_DESIGN_SYSTEM_VERSION,
  apiBaseMode: environment.apiBaseMode,
  requestTimeoutMs: environment.requestTimeoutMs,
});
