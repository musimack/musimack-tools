import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { ApiError, authApi, registerAuthenticationFailureHandler } from '../api/client';
import type { AuthStatus, Permission, Principal } from './contracts';

type AuthContextValue = {
  status: AuthStatus;
  principal: Principal | null;
  signInError: string | null;
  signIn: (email: string, password: string) => Promise<boolean>;
  signOut: () => Promise<void>;
  retry: () => Promise<void>;
  can: (permission: Permission) => boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function statusFor(error: unknown, hasPrincipal: boolean): AuthStatus {
  if (error instanceof ApiError && error.status === 401)
    return hasPrincipal ? 'expired' : 'unauthenticated';
  if (error instanceof ApiError && (error.status === 0 || error.status >= 500))
    return 'unavailable';
  return 'unauthenticated';
}

function signInMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Sign in could not be completed.';
  let message: string;
  if (error.code === 'authentication_rate_limited')
    message = 'Too many attempts. Wait before trying again.';
  else if (
    [
      'authentication_account_locked',
      'authentication_user_inactive',
      'authentication_user_disabled',
    ].includes(error.code)
  )
    message = 'This account cannot sign in. Contact an administrator.';
  else if (error.status === 401) message = 'The email or password is incorrect.';
  else if (error.status === 0 || error.status >= 500)
    message = 'The service is unavailable. Try again shortly.';
  else message = error.message;
  return error.requestId ? `${message} Support reference: ${error.requestId}.` : message;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('initializing');
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [signInError, setSignInError] = useState<string | null>(null);
  const hadAuthenticatedSession = useRef(false);

  useEffect(
    () =>
      registerAuthenticationFailureHandler(() => {
        setPrincipal(null);
        setStatus(hadAuthenticatedSession.current ? 'expired' : 'unauthenticated');
      }),
    [],
  );

  const refresh = useCallback(async () => {
    setStatus('initializing');
    try {
      const identity = await authApi.me();
      setPrincipal(identity);
      hadAuthenticatedSession.current = true;
      setStatus('authenticated');
    } catch (error) {
      setStatus(statusFor(error, hadAuthenticatedSession.current));
      setPrincipal(null);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void authApi.me().then(
      (identity) => {
        if (!active) return;
        setPrincipal(identity);
        hadAuthenticatedSession.current = true;
        setStatus('authenticated');
      },
      (error: unknown) => {
        if (!active) return;
        setStatus(statusFor(error, false));
        setPrincipal(null);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    setSignInError(null);
    try {
      const identity = await authApi.signIn(email, password);
      setPrincipal(identity);
      hadAuthenticatedSession.current = true;
      setStatus('authenticated');
      return true;
    } catch (error) {
      setPrincipal(null);
      hadAuthenticatedSession.current = false;
      setStatus(statusFor(error, false));
      setSignInError(signInMessage(error));
      return false;
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authApi.signOut();
    } finally {
      setPrincipal(null);
      setStatus('unauthenticated');
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      principal,
      signInError,
      signIn,
      signOut,
      retry: refresh,
      can: (permission) => principal?.permissions.includes(permission) ?? false,
    }),
    [principal, refresh, signIn, signInError, signOut, status],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used within AuthProvider.');
  return value;
}
