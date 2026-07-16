import { useState, type SyntheticEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import {
  Button,
  Card,
  FormField,
  PasswordInput,
  TextInput,
  ValidationMessage,
} from '../design-system/components';

export function SignInPage() {
  const { status, signIn, signInError } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [busy, setBusy] = useState(false);
  const from = (location.state as { from?: string } | null)?.from;
  const destination = from?.startsWith('/') ? from : '/';
  if (status === 'authenticated') return <Navigate to={destination} replace />;
  const expired = status === 'expired';
  async function submit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    setBusy(true);
    const data = new FormData(event.currentTarget);
    event.currentTarget.reset();
    const email = data.get('email');
    const password = data.get('password');
    const success = await signIn(
      typeof email === 'string' ? email : '',
      typeof password === 'string' ? password : '',
    );
    setBusy(false);
    if (success) {
      void navigate(destination, { replace: true });
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="brand brand--light">
          <span className="brand__mark" aria-hidden="true">
            M
          </span>
          <div>
            <strong>Musimack</strong>
            <span>SEO Toolkit</span>
          </div>
        </div>
        <div>
          <p className="eyebrow">Private operations console</p>
          <h1>Make technical SEO work feel clear.</h1>
          <p>
            One focused workspace for crawling, sitemap operations, durable history, and retained
            evidence.
          </p>
        </div>
        <small>Authorized internal access only</small>
      </section>
      <section className="auth-form-wrap">
        <Card className="auth-card">
          <p className="eyebrow">Secure workspace</p>
          <h2>{expired ? 'Your session expired' : 'Sign in'}</h2>
          <p>
            {expired
              ? 'Sign in again to continue where you left off.'
              : 'Use your internal Musimack account.'}
          </p>
          <form
            aria-describedby={signInError ? 'sign-in-error' : undefined}
            onSubmit={(event) => {
              void submit(event);
            }}
          >
            <FormField id="email" label="Email address">
              <TextInput
                id="email"
                name="email"
                type="email"
                autoComplete="username"
                required
                disabled={busy}
              />
            </FormField>
            <FormField id="password" label="Password">
              <PasswordInput
                id="password"
                name="password"
                autoComplete="current-password"
                required
                disabled={busy}
                aria-describedby={signInError ? 'sign-in-error' : undefined}
              />
            </FormField>
            {signInError ? (
              <ValidationMessage id="sign-in-error">{signInError}</ValidationMessage>
            ) : null}
            <Button type="submit" disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in securely'}
            </Button>
          </form>
          <p className="auth-note">
            Your session is stored in a secure, HttpOnly cookie. This application never reads or
            stores your password or session token.
          </p>
        </Card>
      </section>
    </main>
  );
}

function MessagePage({
  code,
  title,
  children,
  action = true,
}: {
  code: string;
  title: string;
  children: string;
  action?: boolean;
}) {
  return (
    <main className="centered-page">
      <span className="message-code">{code}</span>
      <h1>{title}</h1>
      <p>{children}</p>
      {action ? (
        <Link className="button" to="/">
          Return to overview
        </Link>
      ) : null}
    </main>
  );
}

export function UnauthorizedPage() {
  return (
    <MessagePage code="403" title="That area is restricted">
      Your account is signed in, but it does not have the permission required for this page.
    </MessagePage>
  );
}
export function NotFoundPage() {
  return (
    <MessagePage code="404" title="Page not found">
      The page may have moved, or the address may be incorrect.
    </MessagePage>
  );
}
export function UnavailablePage() {
  const { retry, status } = useAuth();
  if (status === 'authenticated') return <Navigate to="/" replace />;
  if (status === 'unauthenticated' || status === 'expired') {
    return <Navigate to="/sign-in" replace />;
  }
  return (
    <main className="centered-page">
      <span className="message-code">Offline</span>
      <h1>Service unavailable</h1>
      <p>The private API could not be reached. Check the local service and try again.</p>
      <Button
        onClick={() => {
          void retry();
        }}
      >
        Try again
      </Button>
    </main>
  );
}
