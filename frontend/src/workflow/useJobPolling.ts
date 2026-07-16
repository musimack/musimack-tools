import { useEffect, useRef, useState } from 'react';
import { workflowApi } from './api';
import type { JobProgress, JobStatus } from './contracts';

export const TERMINAL_JOB_STATES = new Set([
  'cancelled',
  'completed',
  'completed_with_warnings',
  'failed',
  'partially_completed',
  'evicted',
]);

export function pollDelayForState(state: string | null, failures: number, hidden: boolean): number {
  const base =
    state === 'queued' || state === 'accepted'
      ? 3000
      : state === 'running' || state === 'starting' || state === 'cancelling'
        ? 2000
        : 5000;
  const backedOff = Math.min(15000, base * Math.max(1, 2 ** Math.min(failures, 3)));
  return hidden ? Math.max(10000, backedOff) : backedOff;
}

export function useJobPolling(jobId: string | undefined) {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refreshRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let timer: number | null = null;
    let failures = 0;
    let currentState: string | null = null;
    let controller: AbortController | null = null;

    const schedule = () => {
      if (stopped || TERMINAL_JOB_STATES.has(currentState ?? '')) return;
      timer = window.setTimeout(run, pollDelayForState(currentState, failures, document.hidden));
    };
    const run = async () => {
      if (stopped || controller) return;
      controller = new AbortController();
      const requestController = controller;
      try {
        const [nextStatus, nextProgress] = await Promise.all([
          workflowApi.status(jobId, controller.signal),
          workflowApi.progress(jobId, controller.signal),
        ]);
        if (requestController.signal.aborted) return;
        currentState = nextStatus.state;
        failures = 0;
        setStatus(nextStatus);
        setProgress(nextProgress);
        setError(null);
      } catch (reason) {
        if (requestController.signal.aborted) return;
        failures += 1;
        setError(reason instanceof Error ? reason.message : 'Progress is temporarily unavailable.');
      } finally {
        controller = null;
        schedule();
      }
    };
    refreshRef.current = () => {
      if (timer !== null) window.clearTimeout(timer);
      void run();
    };
    void run();
    return () => {
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
      controller?.abort();
    };
  }, [jobId]);

  return {
    status,
    progress,
    error,
    refresh: () => {
      refreshRef.current();
    },
  };
}
