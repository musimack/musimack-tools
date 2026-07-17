import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import { ErrorBoundary } from './ErrorBoundary';
import { permissions } from '../auth/contracts';
import { jsonResponse, principalJson, viewerPermissions } from '../test/fixtures';

function renderAt(path: string) {
  window.history.pushState(null, '', path);
  return render(<App />);
}

describe('authenticated application routing', () => {
  test('shows an initialization state while session discovery is pending', () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockReturnValue(new Promise(() => undefined)));
    renderAt('/');
    expect(screen.getByRole('heading', { name: 'Opening your workspace' })).toBeInTheDocument();
  });

  test('redirects an unauthenticated visitor to sign in', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({}, 401)));
    renderAt('/jobs');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  test('shows the service unavailable state for a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline')));
    renderAt('/');
    expect(await screen.findByRole('heading', { name: 'Service unavailable' })).toBeInTheDocument();
  });

  test('renders the overview for an authenticated viewer', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(principalJson())));
    renderAt('/');
    expect(await screen.findByRole('heading', { name: 'Welcome back, River' })).toBeInTheDocument();
    expect(screen.getByText('10 permissions')).toBeInTheDocument();
    expect(screen.getAllByText('viewer@example.test')).toHaveLength(2);
    expect(document.title).toBe('Overview | Musimack SEO Toolkit');
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute(
      'href',
      '#main-content',
    );
  });

  test('shows only navigation allowed by the principal permissions', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(principalJson())));
    renderAt('/');
    expect(await screen.findByRole('navigation')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Jobs' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sitemap Audits' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Link Audits' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Internal Links' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument();
  });

  test('shows Sitemap Audits, Link Audits, and Blog Strategy together when authorized', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(
          principalJson({
            permissions: [...viewerPermissions, 'blog_strategy.view'],
          }),
        ),
      ),
    );
    renderAt('/');
    expect(await screen.findByRole('link', { name: 'Sitemap Audits' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Link Audits' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Blog Strategy' })).toBeInTheDocument();
  });

  test('protects sitemap creation while allowing retained-audit navigation', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(principalJson())));
    renderAt('/sitemap-audits/new');
    expect(
      await screen.findByRole('heading', { name: 'That area is restricted' }),
    ).toBeInTheDocument();
  });

  test('protects link-audit creation while allowing retained-audit navigation', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(principalJson())));
    renderAt('/link-audits/new');
    expect(
      await screen.findByRole('heading', { name: 'That area is restricted' }),
    ).toBeInTheDocument();
  });

  test('allows an operator to open the explicit sitemap creation route', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(
          principalJson({
            role: 'operator',
            permissions: [...viewerPermissions, 'jobs.submit', 'jobs.cancel'],
          }),
        ),
      ),
    );
    renderAt('/sitemap-audits/new');
    expect(await screen.findByRole('heading', { name: 'New sitemap audit' })).toBeInTheDocument();
  });

  test('redirects an authenticated principal lacking a route permission', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(principalJson())));
    renderAt('/users');
    expect(
      await screen.findByRole('heading', { name: 'That area is restricted' }),
    ).toBeInTheDocument();
  });

  test.each([
    ['/jobs', 'Jobs'],
    ['/history', 'History'],
    ['/artifacts', 'Artifacts'],
    ['/settings', 'Settings'],
  ])('renders protected landing page %s', async (path, heading) => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(principalJson())));
    renderAt(path);
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
  });

  test('renders the users page with users.view', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(
          principalJson({
            role: 'administrator',
            permissions: [...viewerPermissions, 'users.view'],
          }),
        ),
      ),
    );
    renderAt('/users');
    expect(await screen.findByRole('heading', { name: 'Users' })).toBeInTheDocument();
  });

  test('shows administrator navigation from returned permissions', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(jsonResponse(principalJson({ role: 'administrator', permissions }))),
    );
    renderAt('/');
    expect(await screen.findByRole('link', { name: 'Users' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument();
  });

  test('does not infer administrator navigation for an operator role', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(
          principalJson({
            role: 'operator',
            permissions: [...viewerPermissions, 'jobs.submit', 'jobs.cancel'],
          }),
        ),
      ),
    );
    renderAt('/');
    expect(await screen.findByRole('link', { name: 'Jobs' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument();
  });

  test('supports the responsive navigation disclosure', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(principalJson())));
    const user = userEvent.setup();
    renderAt('/');
    const toggle = await screen.findByRole('button', { name: 'Menu' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  test('renders a not-found page for an unknown route', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(principalJson())));
    renderAt('/missing');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});

describe('sign-in experience', () => {
  test('submits credentials and returns to the requested route', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ principal: principalJson() }));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    renderAt('/jobs');
    await user.type(await screen.findByLabelText('Email address'), 'viewer@example.test');
    await user.type(screen.getByLabelText('Password'), 'correct horse');
    await user.click(screen.getByRole('button', { name: 'Sign in securely' }));
    expect(await screen.findByRole('heading', { name: 'Jobs' })).toBeInTheDocument();
  });

  test('supports keyboard form submission and clears the password immediately', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({}, 401));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    renderAt('/');
    await user.type(await screen.findByLabelText('Email address'), 'viewer@example.test');
    const password = screen.getByLabelText('Password');
    await user.type(password, 'wrong password{Enter}');
    expect(password).toHaveValue('');
    expect(await screen.findByRole('alert')).toHaveTextContent('incorrect');
  });

  test.each([
    [401, 'authentication_invalid_credentials', 'The email or password is incorrect.'],
    [429, 'authentication_rate_limited', 'Too many attempts. Wait before trying again.'],
    [503, 'internal_api_error', 'The service is unavailable. Try again shortly.'],
    [
      401,
      'authentication_account_locked',
      'This account cannot sign in. Contact an administrator.',
    ],
  ])('shows a safe sign-in error for status %i', async (status, code, message) => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(
        jsonResponse({ error: { code, message: 'unsafe detail', details: [] } }, status),
      );
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    renderAt('/');
    await user.type(await screen.findByLabelText('Email address'), 'viewer@example.test');
    await user.type(screen.getByLabelText('Password'), 'wrong password');
    await user.click(screen.getByRole('button', { name: 'Sign in securely' }));
    expect(screen.getByLabelText('Password')).toHaveValue('');
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
  });

  test('signs out without retaining browser credentials', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(principalJson()))
      .mockResolvedValueOnce(jsonResponse({ signed_out: true }));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    renderAt('/');
    await user.click(await screen.findByText('River Stone'));
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/internal/v1/auth/sign-out',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    );
  });

  test('does not access browser persistence during authentication', async () => {
    const localGet = vi.spyOn(window.localStorage, 'getItem');
    const sessionGet = vi.spyOn(window.sessionStorage, 'getItem');
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({}, 401)));
    renderAt('/');
    await screen.findByRole('heading', { name: 'Sign in' });
    expect(localGet).not.toHaveBeenCalled();
    expect(sessionGet).not.toHaveBeenCalled();
  });

  test('retry recovers the unavailable page', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('offline'))
      .mockResolvedValueOnce(jsonResponse(principalJson()));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    renderAt('/');
    await user.click(await screen.findByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Welcome back, River' })).toBeInTheDocument();
  });
});

describe('global error boundary', () => {
  test('shows a safe recovery page without a stack trace', () => {
    function Broken(): never {
      throw new Error('sensitive stack detail');
    }
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );
    expect(
      screen.getByRole('heading', { name: 'The workspace could not open' }),
    ).toBeInTheDocument();
    expect(screen.queryByText('sensitive stack detail')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload workspace' })).toBeInTheDocument();
  });
});
