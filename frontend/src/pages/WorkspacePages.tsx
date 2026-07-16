import { useAuth } from '../auth/AuthContext';
import { frontendDiagnostics } from '../config/diagnostics';
import { Card, EmptyState, PageHeader, StatusBadge } from '../design-system/components';

export function OverviewPage() {
  const { principal } = useAuth();
  const firstName = principal?.displayName?.split(' ')[0] ?? 'there';
  return (
    <>
      <PageHeader eyebrow="Workspace overview" title={`Welcome back, ${firstName}`}>
        A calm control surface for private SEO operations, durable history, and retained artifacts.
      </PageHeader>
      <div className="metric-grid">
        <Card>
          <span>Access</span>
          <strong>{principal?.role}</strong>
          <small>{principal?.permissions.length ?? 0} permissions</small>
        </Card>
        <Card>
          <span>Session</span>
          <strong>Active</strong>
          <small>Protected by an HttpOnly cookie</small>
        </Card>
        <Card>
          <span>Service boundary</span>
          <strong>Internal v1</strong>
          <small>Same-origin API requests</small>
        </Card>
      </div>
      <Card className="identity-card">
        <p className="eyebrow">Current identity</p>
        <dl>
          <div>
            <dt>Email</dt>
            <dd>{principal?.email ?? 'Not provided'}</dd>
          </div>
          <div>
            <dt>Authentication</dt>
            <dd>{principal?.authenticationMethod ?? 'Unknown'}</dd>
          </div>
          <div>
            <dt>Session expires</dt>
            <dd>
              {principal?.sessionExpiresAt
                ? new Date(principal.sessionExpiresAt).toLocaleString()
                : 'Not provided'}
            </dd>
          </div>
          <div>
            <dt>Frontend</dt>
            <dd>{frontendDiagnostics.frontendVersion}</dd>
          </div>
          <div>
            <dt>API client</dt>
            <dd>{frontendDiagnostics.apiClientVersion}</dd>
          </div>
          <div>
            <dt>Backend availability</dt>
            <dd>Available</dd>
          </div>
        </dl>
      </Card>
      <div className="content-grid">
        <Card>
          <div className="card-heading">
            <div>
              <p className="eyebrow">Operations</p>
              <h2>Ready for focused work</h2>
            </div>
            <StatusBadge tone="positive">Connected</StatusBadge>
          </div>
          <p>
            The foundation intentionally presents read-only landing surfaces. Crawl submission and
            sitemap workflows arrive in Phase 19.
          </p>
        </Card>
        <Card>
          <p className="eyebrow">Security posture</p>
          <h2>Browser-safe sessions</h2>
          <ul className="check-list">
            <li>No tokens in browser storage</li>
            <li>No cookie inspection in JavaScript</li>
            <li>Permission-aware navigation</li>
          </ul>
        </Card>
      </div>
    </>
  );
}

function LandingPage({
  eyebrow,
  title,
  intro,
  emptyTitle,
  children,
}: {
  eyebrow: string;
  title: string;
  intro: string;
  emptyTitle: string;
  children: string;
}) {
  return (
    <>
      <PageHeader eyebrow={eyebrow} title={title}>
        {intro}
      </PageHeader>
      <EmptyState title={emptyTitle}>{children}</EmptyState>
    </>
  );
}

export function JobsPage() {
  return (
    <LandingPage
      eyebrow="Execution"
      title="Jobs"
      intro="A protected home for submitting and monitoring toolkit jobs."
      emptyTitle="Job workflows are coming next"
    >
      This phase establishes the authenticated route and visual language without introducing Phase
      19 execution behavior.
    </LandingPage>
  );
}
export function HistoryPage() {
  return (
    <LandingPage
      eyebrow="Durable records"
      title="History"
      intro="Review the long-lived record of jobs, runs, stages, warnings, and failures."
      emptyTitle="History surface is ready"
    >
      The backend contract is available; browse and filtering interactions remain deliberately
      outside this foundation phase.
    </LandingPage>
  );
}
export function ArtifactsPage() {
  return (
    <LandingPage
      eyebrow="Retained output"
      title="Artifacts"
      intro="A permission-aware destination for generated output and download access."
      emptyTitle="Artifact library is ready"
    >
      Artifact retrieval controls will be connected in a subsequent accepted workflow phase.
    </LandingPage>
  );
}
export function UsersPage() {
  return (
    <LandingPage
      eyebrow="Administration"
      title="Users"
      intro="Manage private workspace identities, roles, lifecycle, and sessions."
      emptyTitle="User administration is protected"
    >
      Only principals with users.view can reach this route. Mutation controls remain outside the
      frontend foundation.
    </LandingPage>
  );
}
export function SettingsPage() {
  return (
    <LandingPage
      eyebrow="Configuration"
      title="Settings"
      intro="Inspect the private toolkit environment and account security options."
      emptyTitle="Settings foundation is ready"
    >
      Account and service settings will be connected through explicit, permission-gated workflows.
    </LandingPage>
  );
}
