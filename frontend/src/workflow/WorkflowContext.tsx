/* eslint-disable react-refresh/only-export-components -- provider and its bounded hook form one module. */
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

type WorkflowContextValue = {
  recentJobIds: readonly string[];
  rememberJob: (jobId: string) => void;
};

const WorkflowContext = createContext<WorkflowContextValue | null>(null);

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [recentJobIds, setRecentJobIds] = useState<readonly string[]>([]);
  const value = useMemo<WorkflowContextValue>(
    () => ({
      recentJobIds,
      rememberJob: (jobId) => {
        setRecentJobIds((current) =>
          [jobId, ...current.filter((item) => item !== jobId)].slice(0, 20),
        );
      },
    }),
    [recentJobIds],
  );
  return <WorkflowContext.Provider value={value}>{children}</WorkflowContext.Provider>;
}

export function useWorkflow() {
  const context = useContext(WorkflowContext);
  if (!context) throw new Error('useWorkflow must be used within WorkflowProvider');
  return context;
}
