import { beforeEach, describe, expect, it, vi } from 'vitest';
import { linkAuditApi } from './api';

const response = (data: unknown) =>
  new Response(JSON.stringify({ link_audit_api_version: 'v1', data }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });

const audit = {
  audit_id: 'link-audit-abc',
  job_id: 'job-abc',
  run_id: 'run-abc',
  seed_url: 'https://example.com/',
  state: 'completed',
  failure_code: null,
  warning_count: 0,
  link_occurrence_count: 4,
  source_target_pair_count: 3,
  target_count: 3,
  working_target_count: 1,
  broken_target_count: 1,
  redirect_target_count: 1,
  unverified_target_count: 0,
  redirect_chain_count: 1,
  redirect_loop_count: 0,
  recommendation_count: 3,
  created_at: '2026-07-17T00:00:00Z',
  completed_at: '2026-07-17T00:00:01Z',
};

describe('link audit API', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('creates and executes exactly one private mutation each', async () => {
    const fetch = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(response(audit)));
    await expect(linkAuditApi.create('run-abc')).resolves.toMatchObject({
      audit_id: 'link-audit-abc',
    });
    await linkAuditApi.execute('link-audit-abc');
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/internal/v1/audits/links');
    expect(fetch.mock.calls[1]?.[0]).toBe('/api/internal/v1/audits/links/link-audit-abc/execute');
  });

  it('validates lifecycle and target action contracts', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ ...audit, state: 'invented' }));
    await expect(linkAuditApi.get('link-audit-abc')).rejects.toMatchObject({
      code: 'invalid_response',
    });
    vi.mocked(globalThis.fetch).mockResolvedValue(
      response({
        items: [{ target_id: 't', target_url: 'https://example.com/x', action: 'invented' }],
        page_size: 50,
      }),
    );
    await expect(linkAuditApi.targets('link-audit-abc')).rejects.toMatchObject({
      code: 'invalid_response',
    });
  });

  it('encodes filters and cursor without credentials in URLs', async () => {
    const fetch = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(response({ items: [], page_size: 2 }));
    await linkAuditApi.targets('link-audit-abc', {
      severity: 'high',
      cursor: 'opaque',
      internal: true,
    });
    const url = fetch.mock.calls[0]?.[0];
    expect(url).toContain('severity=high');
    expect(url).toContain('cursor=opaque');
    expect(url).not.toMatch(/token|password|bearer/iu);
  });

  it('loads every retained inventory and creates all export formats', async () => {
    const fetch = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(response({ items: [], page_size: 50 })));
    await linkAuditApi.occurrences('link-audit-abc');
    await linkAuditApi.chains('link-audit-abc');
    await linkAuditApi.loops('link-audit-abc');
    await linkAuditApi.findings('link-audit-abc');
    await linkAuditApi.recommendations('link-audit-abc');
    await linkAuditApi.exports('link-audit-abc');
    vi.mocked(globalThis.fetch).mockImplementation(() =>
      Promise.resolve(response({ export_id: 'e', artifact_id: 'a' })),
    );
    for (const format of [
      'broken_links_csv',
      'redirect_chains_csv',
      'redirect_map_csv',
      'json',
      'markdown',
    ] as const) {
      await linkAuditApi.export('link-audit-abc', format);
    }
    expect(fetch).toHaveBeenCalledTimes(11);
  });

  it('rejects unsafe identifiers before network access', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    await expect(linkAuditApi.get('../secret')).rejects.toMatchObject({
      code: 'invalid_identifier',
    });
    expect(fetch).not.toHaveBeenCalled();
  });
});
