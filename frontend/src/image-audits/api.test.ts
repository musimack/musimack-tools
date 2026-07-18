import { imageAuditApi } from './api';
import { jsonResponse } from '../test/fixtures';

describe('image-audit API', () => {
  test('uses only the private relative endpoint and validates pages', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ data: { items: [], page_size: 50, next_cursor: null } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(imageAuditApi.list()).resolves.toMatchObject({ items: [], page_size: 50 });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/audits/images',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  test('rejects unsafe identifiers before a request', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>());
    await expect(imageAuditApi.get('../unsafe')).rejects.toMatchObject({
      code: 'invalid_identifier',
    });
    expect(fetch).not.toHaveBeenCalled();
  });
});
