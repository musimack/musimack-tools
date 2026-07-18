import { ApiError, requestJson } from '../api/client';

export type StructuredDataValue = Record<string, unknown>;
export type StructuredDataPage = {
  items: StructuredDataValue[];
  next_cursor: string | null;
  page_size: number;
};
export type StructuredDataFinding = StructuredDataValue & {
  confidence: 'high' | 'medium' | 'low' | 'indeterminate';
  requires_human_review: boolean;
};
export type StructuredDataRecommendation = StructuredDataFinding & {
  scope: string;
  occurrence_count: number;
  affected_page_count: number;
  supporting_finding_ids_json: string;
  supporting_evidence_json: string;
};
export type StructuredDataProfile = StructuredDataValue & {
  profile_version: string;
  observation_state:
    | 'present'
    | 'missing'
    | 'empty'
    | 'invalid'
    | 'conflicting'
    | 'not_applicable'
    | 'indeterminate';
};

const record = (value: unknown): StructuredDataValue => {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    throw new ApiError(
      502,
      'invalid_response',
      'The structured-data response is invalid.',
      null,
      [],
    );
  return value as StructuredDataValue;
};
const data = (value: unknown) => record(value).data;
const id = (value: string) => {
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(value))
    throw new ApiError(0, 'invalid_identifier', 'The identifier is invalid.', null, []);
  return encodeURIComponent(value);
};
const resource = (value: string) => {
  if (
    !/^(blocks|entities|properties|pages|parse-findings|consistency-findings|duplicate-groups|profiles|recommendations)$/u.test(
      value,
    )
  )
    throw new ApiError(0, 'invalid_resource', 'The resource is invalid.', null, []);
  return value;
};
const post = async (path: string, body: unknown) =>
  data(await requestJson(path, { method: 'POST', body: JSON.stringify(body) }));
const query = (values: Record<string, string | null>) => {
  const parameters = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value) parameters.set(key, value);
  });
  return parameters.size ? `?${parameters.toString()}` : '';
};
const page = (value: unknown): StructuredDataPage => {
  const item = record(value);
  if (!Array.isArray(item.items) || typeof item.page_size !== 'number')
    throw new ApiError(502, 'invalid_response', 'The structured-data page is invalid.', null, []);
  return { ...item, items: item.items.map(record) } as StructuredDataPage;
};

export const structuredDataAuditApi = {
  evidence: async (runId: string) =>
    record(data(await requestJson(`/audits/structured-data/evidence/${id(runId)}`))),
  create: async (runId: string) => record(await post('/audits/structured-data', { run_id: runId })),
  execute: async (auditId: string) =>
    record(await post(`/audits/structured-data/${id(auditId)}/execute`, {})),
  list: async () => page(data(await requestJson('/audits/structured-data'))),
  summary: async (auditId: string) =>
    record(data(await requestJson(`/audits/structured-data/${id(auditId)}/summary`))),
  resource: async (auditId: string, name: string, values: Record<string, string | null> = {}) =>
    page(
      data(
        await requestJson(
          `/audits/structured-data/${id(auditId)}/${resource(name)}${query(values)}`,
        ),
      ),
    ),
  exports: async (auditId: string) => {
    const value = record(data(await requestJson(`/audits/structured-data/${id(auditId)}/exports`)));
    return Array.isArray(value.items) ? value.items.map(record) : [];
  },
  export: async (auditId: string, format: string) =>
    record(await post(`/audits/structured-data/${id(auditId)}/exports`, { format })),
};
