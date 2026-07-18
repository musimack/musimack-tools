import { jsonResponse } from '../test/fixtures';
import { structuredDataAuditApi } from './api';

describe('structured-data audit API', () => {
  test('uses only the authenticated private relative endpoint', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ data: { items: [], page_size: 50, next_cursor: null } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(structuredDataAuditApi.list()).resolves.toMatchObject({ items: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/audits/structured-data',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  test('rejects unsafe identifiers and resource paths before a request', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>());
    await expect(structuredDataAuditApi.summary('../unsafe')).rejects.toMatchObject({
      code: 'invalid_identifier',
    });
    await expect(structuredDataAuditApi.resource('audit-1', '../unsafe')).rejects.toMatchObject({
      code: 'invalid_resource',
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  test('creates exports through the bounded POST contract', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        jsonResponse({ data: { id: 'export-1', export_format: 'entity_inventory_csv' } }),
      );
    vi.stubGlobal('fetch', fetchMock);
    await structuredDataAuditApi.export('audit-1', 'entity_inventory_csv');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/audits/structured-data/audit-1/exports',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
