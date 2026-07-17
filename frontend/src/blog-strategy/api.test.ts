import { afterEach, describe, expect, it, vi } from 'vitest';
import { blogStrategyApi } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('blogStrategyApi', () => {
  it('uses only the private BS-01 namespace and unwraps the existing envelope', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ blog_strategy_version: 'blog-strategy-bs01-v1', data: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await expect(blogStrategyApi.projects()).resolves.toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/internal/v1/blog-strategy/projects',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('does not retry a manual page mutation', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { page_id: 'bpg_1' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await expect(blogStrategyApi.addPage('bsp_1', 'https://example.com/post')).resolves.toEqual({
      page_id: 'bpg_1',
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
