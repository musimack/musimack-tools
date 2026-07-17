import { requestJson } from '../api/client';
import { environment } from '../config/environment';

type RecordValue = Record<string, unknown>;
function data(value: unknown): unknown {
  if (typeof value !== 'object' || value === null || !('data' in value))
    throw new Error('invalid_blog_strategy_response');
  return value.data;
}

export type Project = {
  project_id: string;
  client_name: string;
  primary_website: string;
  primary_market: string;
  status: string;
  revision: number;
  counts: {
    included_pages: number;
    classified_pages: number;
    topic_families: number;
    open_overlaps: number;
    approved_decisions: number;
  };
  updated_at: string;
};

function project(value: unknown): Project {
  if (typeof value !== 'object' || value === null) throw new Error('invalid_blog_strategy_project');
  return value as Project;
}

export const blogStrategyApi = {
  async projects(): Promise<readonly Project[]> {
    const value = data(await requestJson('/blog-strategy/projects'));
    if (!Array.isArray(value)) throw new Error('invalid_blog_strategy_projects');
    return value.map(project);
  },
  async createProject(payload: RecordValue): Promise<Project> {
    return project(
      data(
        await requestJson('/blog-strategy/projects', {
          method: 'POST',
          body: JSON.stringify({ data: payload }),
        }),
      ),
    );
  },
  async pages(projectId: string): Promise<readonly RecordValue[]> {
    const value = data(await requestJson(`/blog-strategy/projects/${projectId}/pages`));
    if (!Array.isArray(value)) throw new Error('invalid_blog_strategy_pages');
    return value as RecordValue[];
  },
  async addPage(projectId: string, url: string): Promise<RecordValue> {
    return data(
      await requestJson(`/blog-strategy/projects/${projectId}/pages`, {
        method: 'POST',
        body: JSON.stringify({ data: { url, inclusion_state: 'needs_review' } }),
      }),
    ) as RecordValue;
  },
  async readiness(projectId: string): Promise<{ ready: boolean; warnings: readonly string[] }> {
    return data(await requestJson(`/blog-strategy/projects/${projectId}/readiness`)) as {
      ready: boolean;
      warnings: readonly string[];
    };
  },
  async updatePage(projectId: string, pageId: string, revision: number, payload: RecordValue) {
    return data(
      await requestJson(`/blog-strategy/projects/${projectId}/pages/${pageId}`, {
        method: 'PATCH',
        body: JSON.stringify({ data: payload, revision }),
      }),
    ) as RecordValue;
  },
  async approvePage(projectId: string, pageId: string, revision: number, approved: boolean) {
    return data(
      await requestJson(`/blog-strategy/projects/${projectId}/pages/${pageId}/approve`, {
        method: 'POST',
        body: JSON.stringify({ data: { approved }, revision }),
      }),
    ) as RecordValue;
  },
  async families(projectId: string): Promise<readonly RecordValue[]> {
    const value = data(await requestJson(`/blog-strategy/projects/${projectId}/topic-families`));
    if (!Array.isArray(value)) throw new Error('invalid_blog_strategy_families');
    return value as RecordValue[];
  },
  async createFamily(projectId: string, name: string) {
    return data(
      await requestJson(`/blog-strategy/projects/${projectId}/topic-families`, {
        method: 'POST',
        body: JSON.stringify({ data: { name } }),
      }),
    ) as RecordValue;
  },
  async overlaps(projectId: string): Promise<readonly RecordValue[]> {
    const value = data(await requestJson(`/blog-strategy/projects/${projectId}/overlaps`));
    if (!Array.isArray(value)) throw new Error('invalid_blog_strategy_overlaps');
    return value as RecordValue[];
  },
  async createOverlap(projectId: string, payload: RecordValue) {
    return data(
      await requestJson(`/blog-strategy/projects/${projectId}/overlaps`, {
        method: 'POST',
        body: JSON.stringify({ data: payload }),
      }),
    ) as RecordValue;
  },
  async exportWorkbook(projectId: string, acknowledgeWarnings: boolean): Promise<void> {
    const response = await fetch(
      `${environment.apiBaseUrl}/blog-strategy/projects/${projectId}/export`,
      {
        method: 'POST',
        credentials: 'include',
        headers: {
          Accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ data: { acknowledge_warnings: acknowledgeWarnings } }),
      },
    );
    if (!response.ok) throw new Error('blog_strategy_export_failed');
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download =
      response.headers.get('content-disposition')?.match(/filename="([^"]+)"/u)?.[1] ??
      'blog-strategy.xlsx';
    link.click();
    URL.revokeObjectURL(url);
  },
};
