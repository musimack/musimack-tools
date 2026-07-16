import { ApiError, authApi, parsePrincipal, request, requestJson } from './client';
import { jsonResponse, principalJson } from '../test/fixtures';

describe('frontend API client', () => {
  test('loads the current principal with included credentials', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(principalJson()));
    vi.stubGlobal('fetch', fetchMock);
    const principal = await authApi.me();
    expect(principal.displayName).toBe('River Stone');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/auth/me',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  test('sends sign-in credentials only in the JSON request body', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ principal: principalJson() }));
    vi.stubGlobal('fetch', fetchMock);
    await authApi.signIn('viewer@example.test', 'correct horse');
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe('POST');
    expect(init?.body).toBe(
      JSON.stringify({ email: 'viewer@example.test', password: 'correct horse' }),
    );
    expect(new Headers(init?.headers).has('Authorization')).toBe(false);
  });

  test('normalizes a structured backend error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(
          {
            request_id: 'req-123',
            error: {
              code: 'request_validation_failed',
              message: 'The request schema is invalid.',
              details: [{ code: 'invalid', message: 'The field is invalid.', field: 'email' }],
            },
          },
          400,
        ),
      ),
    );
    await expect(requestJson('/anything')).rejects.toMatchObject({
      status: 400,
      code: 'request_validation_failed',
      requestId: 'req-123',
      details: [{ field: 'email' }],
    });
  });

  test.each([401, 403, 404, 409, 422, 429, 500])(
    'preserves handled HTTP status %i',
    async (status) => {
      vi.stubGlobal(
        'fetch',
        vi
          .fn<typeof fetch>()
          .mockResolvedValue(
            jsonResponse(
              { error: { code: 'bounded_error', message: 'The request failed.', details: [] } },
              status,
            ),
          ),
      );
      await expect(requestJson('/anything')).rejects.toMatchObject({
        status,
        code: 'bounded_error',
      });
    },
  );

  test('notifies the authentication boundary once on 401', async () => {
    const handler = vi.fn();
    const unregister = (await import('./client')).registerAuthenticationFailureHandler(handler);
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({}, 401)));
    await expect(requestJson('/anything')).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledOnce();
    unregister();
  });

  test('uses a bounded error for non-JSON failures', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(new Response('proxy error', { status: 502 })),
    );
    await expect(requestJson('/anything')).rejects.toMatchObject({
      status: 502,
      code: 'request_failed',
    });
  });

  test('normalizes network failures without leaking exception text', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockRejectedValue(new Error('secret endpoint')));
    await expect(requestJson('/anything')).rejects.toEqual(
      expect.objectContaining({ status: 0, code: 'service_unavailable' }),
    );
  });

  test('captures a safe correlation ID on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-safe_123' },
        }),
      ),
    );
    await expect(request('/anything')).resolves.toMatchObject({
      correlationId: 'req-safe_123',
      status: 200,
    });
  });

  test('rejects an unsafe correlation ID', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json', 'X-Request-ID': '<unsafe>' },
        }),
      ),
    );
    await expect(request('/anything')).resolves.toMatchObject({ correlationId: null });
  });

  test('accepts an empty successful response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 })),
    );
    await expect(requestJson('/anything')).resolves.toBeNull();
  });

  test('rejects an unexpected successful content type', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          new Response('<html></html>', { status: 200, headers: { 'Content-Type': 'text/html' } }),
        ),
    );
    await expect(requestJson('/anything')).rejects.toMatchObject({
      code: 'unexpected_content_type',
    });
  });

  test('supports caller cancellation', async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockImplementation(
        (_input, init) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
              reject(new DOMException('aborted', 'AbortError'));
            });
          }),
      ),
    );
    const pending = request('/anything', { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ code: 'request_cancelled' });
  });

  test('applies a bounded request timeout', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockImplementation(
        (_input, init) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
              reject(new DOMException('aborted', 'AbortError'));
            });
          }),
      ),
    );
    const pending = request('/anything', { timeoutMs: 50 });
    const assertion = expect(pending).rejects.toMatchObject({ code: 'request_timeout' });
    await vi.advanceTimersByTimeAsync(50);
    await assertion;
    vi.useRealTimers();
  });

  test.each(['https://example.test/api', '//example.test/api', '/safe\nunsafe'])(
    'rejects untrusted request path %s',
    async (path) => {
      await expect(request(path)).rejects.toMatchObject({ code: 'invalid_request_path' });
    },
  );

  test.each([
    ['unknown role', { role: 'owner' }],
    ['unknown permission', { permissions: ['jobs.view', 'system.root'] }],
    ['missing versions', { session_version: null }],
  ])('rejects an invalid principal: %s', (_name, override) => {
    expect(() => parsePrincipal(principalJson(override))).toThrow(ApiError);
  });

  test('maps snake-case backend identity fields to frontend fields', () => {
    expect(parsePrincipal(principalJson())).toMatchObject({
      userId: 'user-1',
      authenticationMethod: 'password_session',
      passwordChangeAvailable: true,
    });
  });
});
