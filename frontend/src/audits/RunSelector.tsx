import type { MetadataAuditRunCandidate } from './contracts';

function readable(value: string): string {
  return value.replaceAll('_', ' ');
}

function completedAt(value: string | null): string {
  return value ? new Date(value).toLocaleString() : 'Completion time unavailable';
}

export function MetadataAuditRunSelector({
  candidates,
  selectedRunId,
  search,
  onSearch,
  onSelect,
}: {
  candidates: MetadataAuditRunCandidate[];
  selectedRunId: string;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (runId: string) => void;
}) {
  const normalized = search.trim().toLocaleLowerCase();
  const visible = candidates.filter((candidate) =>
    [
      candidate.seed_url,
      candidate.completed_at ?? '',
      candidate.job_status,
      candidate.crawl_profile,
      candidate.run_id,
    ].some((value) => value.toLocaleLowerCase().includes(normalized)),
  );
  return (
    <fieldset>
      <legend>Completed crawl</legend>
      <label htmlFor="metadata-run-search">Search by site, status, profile, or date</label>
      <input
        id="metadata-run-search"
        type="search"
        value={search}
        onChange={(event) => {
          onSearch(event.target.value);
        }}
        placeholder="example.com or completed with warnings"
      />
      {candidates.length === 0 ? (
        <p>No completed runs with retained page evidence are available.</p>
      ) : visible.length === 0 ? (
        <p>No runs match this search.</p>
      ) : (
        <div className="option-grid" aria-label="Crawl runs">
          {visible.map((candidate) => {
            const inputId = `metadata-run-${candidate.run_id}`;
            return (
              <label key={candidate.run_id} htmlFor={inputId}>
                <input
                  id={inputId}
                  type="radio"
                  name="metadata-run"
                  value={candidate.run_id}
                  checked={selectedRunId === candidate.run_id}
                  disabled={!candidate.eligible}
                  onChange={() => {
                    onSelect(candidate.run_id);
                  }}
                />
                <strong>{candidate.seed_url}</strong>
                <span>{completedAt(candidate.completed_at)}</span>
                <span>
                  {readable(candidate.job_status)} · {readable(candidate.crawl_profile)} ·{' '}
                  {candidate.page_evidence_count.toLocaleString()} pages
                </span>
                <span>Evidence: {readable(candidate.evidence_state)}</span>
                <small>Run ID: {candidate.run_id}</small>
                {!candidate.eligible ? (
                  <span role="note">
                    {candidate.ineligibility_reason ?? 'This run cannot be used.'}
                  </span>
                ) : null}
              </label>
            );
          })}
        </div>
      )}
    </fieldset>
  );
}
