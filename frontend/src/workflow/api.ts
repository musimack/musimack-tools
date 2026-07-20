import { ApiError, requestJson } from '../api/client';
import { environment } from '../config/environment';
import type {
  ApiCrawlRequest,
  Artifact,
  CrawlRequest,
  HistoricalJob,
  HistoricalRun,
  JobList,
  JobProgress,
  JobResult,
  JobState,
  JobStatus,
  Page,
  PreflightResult,
  RecommendationPage,
  RecommendationDetail,
  ValidationReport,
} from './contracts';

type RecordValue = Record<string, unknown>;
const API = '';
const jobStates = new Set<JobState>([
  'accepted',
  'queued',
  'starting',
  'running',
  'cancelling',
  'cancelled',
  'completed',
  'completed_with_warnings',
  'failed',
  'partially_completed',
  'evicted',
]);
const recommendationStates = new Set(['include', 'exclude', 'review', 'indeterminate']);

function record(value: unknown): RecordValue {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new ApiError(
      502,
      'invalid_response',
      'The service returned an invalid response.',
      null,
      [],
    );
  }
  return value as RecordValue;
}
// The generic binds each endpoint's explicit contract at the envelope boundary.
// eslint-disable-next-line @typescript-eslint/no-unnecessary-type-parameters
function data<T>(value: unknown): T {
  const envelope = record(value);
  return record(envelope.data) as T;
}
function id(value: string): string {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The identifier is invalid.', null, []);
  return encodeURIComponent(value);
}
function query(values: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
  });
  const result = params.toString();
  return result ? `?${result}` : '';
}
function parseStatus(value: unknown): JobStatus {
  const item = record(value);
  if (
    typeof item.outcome !== 'string' ||
    typeof item.urls_discovered !== 'number' ||
    typeof item.urls_fetched !== 'number' ||
    typeof item.terminal !== 'boolean' ||
    typeof item.result_available !== 'boolean'
  )
    throw new ApiError(
      502,
      'invalid_response',
      'The service returned an invalid job status.',
      null,
      [],
    );
  const state =
    typeof item.state === 'string' && jobStates.has(item.state as JobState)
      ? item.state
      : item.state === null
        ? null
        : 'unknown';
  return { ...item, state } as JobStatus;
}
function parseValidation(value: unknown): ValidationReport {
  const item = record(value);
  if (
    typeof item.valid !== 'boolean' ||
    !Array.isArray(item.issues) ||
    typeof item.selected_profile !== 'string'
  )
    throw new ApiError(
      502,
      'invalid_response',
      'The service returned an invalid validation report.',
      null,
      [],
    );
  return item as ValidationReport;
}
function parseRecommendationPage(value: unknown): RecommendationPage {
  const page = record(value);
  if (
    !Array.isArray(page.items) ||
    typeof page.total !== 'number' ||
    typeof page.has_more !== 'boolean'
  )
    throw new ApiError(
      502,
      'invalid_response',
      'The service returned an invalid recommendation page.',
      null,
      [],
    );
  page.items.forEach((value) => {
    const item = record(value);
    if (
      typeof item.url !== 'string' ||
      typeof item.sequence !== 'number' ||
      typeof item.state !== 'string' ||
      !recommendationStates.has(item.state)
    )
      throw new ApiError(
        502,
        'invalid_response',
        'The service returned an invalid recommendation.',
        null,
        [],
      );
  });
  return page as RecommendationPage;
}
function parseRecommendationDetail(value: unknown): RecommendationDetail {
  const detail = record(value);
  const recommendation = record(detail.recommendation);
  if (
    typeof recommendation.sequence !== 'number' ||
    typeof recommendation.url !== 'string' ||
    typeof recommendation.state !== 'string' ||
    !recommendationStates.has(recommendation.state) ||
    !Array.isArray(detail.reason_codes) ||
    !Array.isArray(detail.rule_evidence) ||
    !Array.isArray(detail.warning_details) ||
    !Array.isArray(detail.redirect_chain)
  )
    throw new ApiError(
      502,
      'invalid_response',
      'The service returned an invalid recommendation detail.',
      null,
      [],
    );
  return detail as RecommendationDetail;
}
async function post<T>(path: string, payload?: unknown): Promise<T> {
  return data<T>(
    await requestJson(path, {
      method: 'POST',
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
    }),
  );
}

export function serializeCrawlRequest(request: CrawlRequest): ApiCrawlRequest {
  const { overrides: formOverrides, existing_file_policy: existingFilePolicy, ...fields } = request;
  const overrides = {
    ...(formOverrides.max_urls === null ? {} : { maximum_urls: formOverrides.max_urls }),
    ...(formOverrides.max_depth === null ? {} : { maximum_depth: formOverrides.max_depth }),
    ...(formOverrides.max_duration === null
      ? {}
      : { maximum_duration_seconds: formOverrides.max_duration }),
    ...(formOverrides.max_accepted_bytes === null
      ? {}
      : { maximum_accepted_bytes: formOverrides.max_accepted_bytes }),
    ...(formOverrides.max_concurrency === null
      ? {}
      : { maximum_concurrency: formOverrides.max_concurrency }),
    ...(formOverrides.max_queue === null ? {} : { maximum_queue_size: formOverrides.max_queue }),
    ...(formOverrides.min_delay === null
      ? {}
      : { minimum_request_delay_seconds: formOverrides.min_delay }),
    ...(formOverrides.max_redirect_hops === null
      ? {}
      : { maximum_redirect_hops: formOverrides.max_redirect_hops }),
    ...(formOverrides.max_response_bytes === null
      ? {}
      : { maximum_response_bytes: formOverrides.max_response_bytes }),
  };
  return {
    ...fields,
    overrides,
    existing_file_policy: existingFilePolicy === 'fail' ? 'fail_if_exists' : 'overwrite',
  };
}

export const workflowApi = {
  validate: async (request: CrawlRequest) =>
    parseValidation(
      await post<unknown>(`${API}/requests/validate`, serializeCrawlRequest(request)),
    ),
  preflight: (request: CrawlRequest) =>
    post<PreflightResult>(`${API}/requests/preflight`, serializeCrawlRequest(request)),
  submit: async (request: CrawlRequest) => {
    const submission = record(await post<unknown>(`${API}/jobs`, serializeCrawlRequest(request)));
    return { outcome: String(submission.outcome), status: parseStatus(submission.status) };
  },
  jobs: async (): Promise<JobList> => {
    const result = data<RecordValue>(await requestJson(`${API}/jobs`));
    if (
      !Array.isArray(result.items) ||
      typeof result.truncated !== 'boolean' ||
      typeof result.maximum !== 'number'
    )
      throw new ApiError(
        502,
        'invalid_response',
        'The service returned an invalid job list.',
        null,
        [],
      );
    return {
      items: result.items.map(parseStatus),
      truncated: result.truncated,
      maximum: result.maximum,
    };
  },
  status: async (jobId: string, signal?: AbortSignal): Promise<JobStatus> =>
    parseStatus(data(await requestJson(`${API}/jobs/${id(jobId)}`, signal ? { signal } : {}))),
  progress: async (jobId: string, signal?: AbortSignal): Promise<JobProgress> =>
    data<JobProgress>(
      await requestJson(
        `${API}/jobs/${id(jobId)}/progress?history_limit=25`,
        signal ? { signal } : {},
      ),
    ),
  result: async (jobId: string): Promise<JobResult> =>
    data<JobResult>(await requestJson(`${API}/jobs/${id(jobId)}/result`)),
  cancel: (jobId: string) =>
    post<{ outcome: string; status: JobStatus | null; message: string }>(
      `${API}/jobs/${id(jobId)}/cancel`,
    ),
  capabilities: async (): Promise<{ supported: string[]; unsupported: string[] }> =>
    data(await requestJson(`${API}/capabilities`)),
  recommendations: async (
    jobId: string,
    values: { offset?: number; limit?: number; state?: string; reason?: string; text?: string },
  ): Promise<RecommendationPage> =>
    parseRecommendationPage(
      data(await requestJson(`${API}/jobs/${id(jobId)}/recommendations${query(values)}`)),
    ),
  recommendation: async (jobId: string, sequence: number): Promise<RecommendationDetail> => {
    if (!Number.isInteger(sequence) || sequence < 1 || sequence > 50_000)
      throw new ApiError(
        400,
        'invalid_identifier',
        'The recommendation identifier is invalid.',
        null,
        [],
      );
    return parseRecommendationDetail(
      data(await requestJson(`${API}/jobs/${id(jobId)}/recommendations/${String(sequence)}`)),
    );
  },
  artifacts: async (
    offset = 0,
    limit = 50,
  ): Promise<{ items: Artifact[]; offset: number; limit: number }> =>
    data(await requestJson(`${API}/artifacts${query({ offset, limit })}`)),
  artifact: async (artifactId: string): Promise<Artifact> =>
    data<Artifact>(await requestJson(`${API}/artifacts/${id(artifactId)}`)),
  historyJobs: async (
    values: Record<string, string | number | boolean | null | undefined> = {},
  ): Promise<Page<HistoricalJob>> =>
    data<Page<HistoricalJob>>(await requestJson(`${API}/history/jobs${query(values)}`)),
  historyJob: async (jobId: string): Promise<HistoricalJob> =>
    data<HistoricalJob>(await requestJson(`${API}/history/jobs/${id(jobId)}`)),
  historyRuns: async (
    values: Record<string, string | number | boolean | null | undefined> = {},
  ): Promise<Page<HistoricalRun>> =>
    data<Page<HistoricalRun>>(await requestJson(`${API}/history/runs${query(values)}`)),
  historyRun: async (runId: string): Promise<HistoricalRun> =>
    data<HistoricalRun>(await requestJson(`${API}/history/runs/${id(runId)}`)),
  related: async (runId: string, kind: 'stages' | 'warnings' | 'failures' | 'artifacts') =>
    data<{ items: RecordValue[] }>(await requestJson(`${API}/history/runs/${id(runId)}/${kind}`)),
};

export async function downloadArtifact(
  artifactId: string,
  fallbackFilename: string,
): Promise<void> {
  const safeId = id(artifactId);
  const response = await fetch(`${environment.apiBaseUrl}/artifacts/${safeId}/download`, {
    credentials: 'include',
    headers: { Accept: 'application/octet-stream' },
  });
  if (!response.ok)
    throw new ApiError(
      response.status,
      'download_failed',
      'The artifact could not be downloaded.',
      null,
      [],
    );
  const disposition = response.headers.get('content-disposition') ?? '';
  const match = /filename="([^"\\/\r\n]{1,255})"/iu.exec(disposition);
  const filename = match?.[1] ?? fallbackFilename.replace(/[^A-Za-z0-9._-]/gu, '_');
  const url = URL.createObjectURL(await response.blob());
  try {
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    anchor.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}
