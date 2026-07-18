import { jsonResponse } from '../test/fixtures';
import { migrationQaApi } from './api';

describe('website migration QA API', () => {
  test('uses only the authenticated private relative endpoint', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        jsonResponse({ data: { items: [], page_size: 50, next_cursor: null, total: 0 } }),
      );
    vi.stubGlobal('fetch', fetchMock);
    await expect(migrationQaApi.list()).resolves.toMatchObject({ items: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/migrations/qa',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  test('rejects unsafe identifiers and resource paths before a request', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>());
    await expect(migrationQaApi.summary('../unsafe')).rejects.toMatchObject({
      code: 'invalid_identifier',
    });
    await expect(migrationQaApi.resource('project-1', '../unsafe')).rejects.toMatchObject({
      code: 'invalid_resource',
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  test.each([
    'findings_csv',
    'redirects_csv',
    'mappings_csv',
    'comparisons_csv',
    'recommendations_csv',
    'sitewide_csv',
    'json',
    'markdown',
  ])('creates the %s export through the bounded POST contract', async (format) => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ data: { id: 'export-1', export_format: format } }));
    vi.stubGlobal('fetch', fetchMock);
    await migrationQaApi.export('project-1', format);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/migrations/qa/project-1/exports',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ format }) }),
    );
  });
});
