import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { requestJson } from '../api/client';
import { jsonResponse, principalJson } from '../test/fixtures';
import { AuthProvider, useAuth } from './AuthContext';

function Harness() {
  const { status } = useAuth();
  return (
    <>
      <span>{status}</span>
      <button
        type="button"
        onClick={() => {
          void requestJson('/protected').catch(() => undefined);
        }}
      >
        Protected request
      </button>
    </>
  );
}

describe('authentication state integration', () => {
  test('collapses an authenticated API 401 into the expired state', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(principalJson()))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            error: {
              code: 'authentication_required',
              message: 'Authentication required.',
              details: [],
            },
          },
          401,
        ),
      );
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );
    expect(await screen.findByText('authenticated')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Protected request' }));
    expect(await screen.findByText('expired')).toBeInTheDocument();
  });
});
