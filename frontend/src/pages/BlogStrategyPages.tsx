import { type SyntheticEvent, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { blogStrategyApi, type Project } from '../blog-strategy/api';
import { useAuth } from '../auth/AuthContext';
import {
  Alert,
  Button,
  Card,
  EmptyState,
  FormField,
  PageHeader,
  StatusBadge,
  TableFoundation,
  TextInput,
} from '../design-system/components';

export function BlogStrategyProjectsPage() {
  const [projects, setProjects] = useState<readonly Project[]>([]);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    void blogStrategyApi
      .projects()
      .then(setProjects)
      .catch(() => {
        setError('Projects could not be loaded.');
      });
  }, []);

  async function create(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setCreating(true);
    setError('');
    try {
      const created = await blogStrategyApi.createProject({
        client_name: values.get('client'),
        primary_website: values.get('website'),
        primary_market: values.get('market'),
      });
      setProjects((current) => [created, ...current]);
      event.currentTarget.reset();
    } catch {
      setError('Check the client, website, and market values.');
    } finally {
      setCreating(false);
    }
  }

  return (
    <section>
      <PageHeader eyebrow="Blog Strategy · BS-01" title="Client blog organization">
        Build a manually reviewed inventory before competitor or AI research.
      </PageHeader>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <Card>
        <h2>Create project</h2>
        <form className="form-grid" onSubmit={(event) => void create(event)}>
          <FormField label="Client" id="client">
            <TextInput id="client" name="client" required />
          </FormField>
          <FormField label="Website" id="website">
            <TextInput id="website" name="website" type="url" required />
          </FormField>
          <FormField label="Primary market" id="market">
            <TextInput id="market" name="market" required />
          </FormField>
          <Button disabled={creating}>{creating ? 'Creating…' : 'Create project'}</Button>
        </form>
      </Card>
      <Card>
        <h2>Projects</h2>
        {projects.length === 0 ? (
          <EmptyState title="No Blog Strategy projects">
            Create the first internal project above.
          </EmptyState>
        ) : (
          <TableFoundation>
            <thead>
              <tr>
                <th>Client</th>
                <th>Website</th>
                <th>Status</th>
                <th>Pages</th>
                <th>Classified</th>
                <th>Families</th>
                <th>Open concerns</th>
                <th>Approved</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((item) => (
                <tr key={item.project_id}>
                  <td>
                    <Link to={`/blog-strategy/${item.project_id}`}>{item.client_name}</Link>
                  </td>
                  <td>{item.primary_website}</td>
                  <td>
                    <StatusBadge tone="neutral">{item.status}</StatusBadge>
                  </td>
                  <td>{item.counts.included_pages}</td>
                  <td>{item.counts.classified_pages}</td>
                  <td>{item.counts.topic_families}</td>
                  <td>{item.counts.open_overlaps}</td>
                  <td>{item.counts.approved_decisions}</td>
                </tr>
              ))}
            </tbody>
          </TableFoundation>
        )}
      </Card>
    </section>
  );
}

export function BlogStrategyProjectPage() {
  const { can } = useAuth();
  const { projectId = '' } = useParams();
  const [pages, setPages] = useState<readonly Record<string, unknown>[]>([]);
  const [families, setFamilies] = useState<readonly Record<string, unknown>[]>([]);
  const [overlaps, setOverlaps] = useState<readonly Record<string, unknown>[]>([]);
  const [warnings, setWarnings] = useState<readonly string[]>([]);
  const [error, setError] = useState('');
  const refresh = async () => {
    const [nextPages, readiness, nextFamilies, nextOverlaps] = await Promise.all([
      blogStrategyApi.pages(projectId),
      blogStrategyApi.readiness(projectId),
      blogStrategyApi.families(projectId),
      blogStrategyApi.overlaps(projectId),
    ]);
    setPages(nextPages);
    setWarnings(readiness.warnings);
    setFamilies(nextFamilies);
    setOverlaps(nextOverlaps);
  };
  useEffect(() => {
    void Promise.all([
      blogStrategyApi.pages(projectId),
      blogStrategyApi.readiness(projectId),
      blogStrategyApi.families(projectId),
      blogStrategyApi.overlaps(projectId),
    ]).then(
      ([nextPages, readiness, nextFamilies, nextOverlaps]) => {
        setPages(nextPages);
        setWarnings(readiness.warnings);
        setFamilies(nextFamilies);
        setOverlaps(nextOverlaps);
      },
      () => {
        setError('This project could not be loaded.');
      },
    );
  }, [projectId]);
  async function add(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    const form = event.currentTarget;
    const rawUrl = new FormData(form).get('url');
    const url = typeof rawUrl === 'string' ? rawUrl : '';
    try {
      await blogStrategyApi.addPage(projectId, url);
      form.reset();
      await refresh();
    } catch {
      setError('The URL is invalid or already exists in this project.');
    }
  }
  async function createFamily(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    const form = event.currentTarget;
    const raw = new FormData(form).get('name');
    try {
      await blogStrategyApi.createFamily(projectId, typeof raw === 'string' ? raw : '');
      form.reset();
      await refresh();
    } catch {
      setError('The topic family could not be created.');
    }
  }
  async function createOverlap(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const rawIds = values.get('page_ids');
    try {
      await blogStrategyApi.createOverlap(projectId, {
        page_ids: typeof rawIds === 'string' ? rawIds.split(',').map((item) => item.trim()) : [],
        concern_type: values.get('concern_type'),
        severity: values.get('severity'),
        notes: values.get('notes'),
      });
      form.reset();
      await refresh();
    } catch {
      setError('Use two or more valid comma-separated page IDs.');
    }
  }
  return (
    <section>
      <PageHeader eyebrow="Blog Strategy · Project" title="Inventory and decisions">
        Client Content → Classifications → Topic Families → Manual Overlap Review → Strategy
        Decisions → Export
      </PageHeader>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {!can('blog_strategy.review') ? (
        <Alert>You have read-only Blog Strategy access.</Alert>
      ) : null}
      {warnings.length ? (
        <Alert tone="warning">Export readiness: {warnings.join(', ').replaceAll('_', ' ')}</Alert>
      ) : (
        <Alert>The project is ready to export.</Alert>
      )}
      <Card>
        <h2>Manual URL intake</h2>
        <form className="form-grid" onSubmit={(event) => void add(event)}>
          <FormField label="Blog page URL" id="page-url">
            <TextInput id="page-url" name="url" type="url" required />
          </FormField>
          <Button>Add page</Button>
        </form>
      </Card>
      <Card>
        <h2>Client Content</h2>
        {pages.length === 0 ? (
          <EmptyState title="No pages yet">
            Add pages manually or use the evidence import boundary.
          </EmptyState>
        ) : (
          <TableFoundation>
            <thead>
              <tr>
                <th>Page</th>
                <th>Inclusion</th>
                <th>Topic</th>
                <th>Intent</th>
                <th>Role</th>
                <th>Family</th>
                <th>Claim risk</th>
                <th>Action</th>
                <th>Approval</th>
              </tr>
            </thead>
            <tbody>
              {pages.map((page) => (
                <PageEditor
                  key={String(page.page_id)}
                  page={page}
                  families={families}
                  canReview={can('blog_strategy.review')}
                  canApprove={can('blog_strategy.approve')}
                  onSave={async (payload) => {
                    const { approved, ...review } = payload;
                    const updated = await blogStrategyApi.updatePage(
                      projectId,
                      display(page.page_id),
                      Number(page.revision),
                      review,
                    );
                    if (typeof approved === 'boolean' && approved !== Boolean(page.approved)) {
                      await blogStrategyApi.approvePage(
                        projectId,
                        display(page.page_id),
                        Number(updated.revision),
                        approved,
                      );
                    }
                    await refresh();
                  }}
                />
              ))}
            </tbody>
          </TableFoundation>
        )}
      </Card>
      <Card>
        <h2>Topic Families</h2>
        <form className="form-grid" onSubmit={(event) => void createFamily(event)}>
          <FormField id="family-name" label="Family name">
            <TextInput id="family-name" name="name" required />
          </FormField>
          <Button>Create family</Button>
        </form>
        <p>
          {families.length
            ? families.map((item) => display(item.name)).join(', ')
            : 'No topic families yet.'}
        </p>
      </Card>
      <Card>
        <h2>Manual Overlap Review</h2>
        <form className="form-grid" onSubmit={(event) => void createOverlap(event)}>
          <FormField id="overlap-pages" label="Page IDs (comma-separated)">
            <TextInput id="overlap-pages" name="page_ids" required />
          </FormField>
          <label>
            Concern type
            <select name="concern_type" defaultValue="possible_overlap">
              <option value="possible_overlap">Possible overlap</option>
              <option value="possible_duplicate">Possible duplicate</option>
              <option value="service_page_conflict">Service-page conflict</option>
            </select>
          </label>
          <label>
            Severity
            <select name="severity" defaultValue="medium">
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <FormField id="overlap-notes" label="Evidence and notes">
            <TextInput id="overlap-notes" name="notes" />
          </FormField>
          <Button>Record concern</Button>
        </form>
        <p>{overlaps.length} manual concern(s). Human review remains authoritative.</p>
      </Card>
      <Card>
        <h2>Export</h2>
        <p>One included page per row. Warnings require explicit acknowledgement.</p>
        <Button
          onClick={() =>
            void blogStrategyApi.exportWorkbook(projectId, warnings.length > 0).catch(() => {
              setError('The workbook could not be created.');
            })
          }
        >
          Create one-sheet XLSX
        </Button>
      </Card>
    </section>
  );
}

function PageEditor({
  page,
  families,
  canReview,
  canApprove,
  onSave,
}: {
  page: Record<string, unknown>;
  families: readonly Record<string, unknown>[];
  canReview: boolean;
  canApprove: boolean;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
}) {
  async function save(event: SyntheticEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    await onSave({
      inclusion_state: values.get('inclusion_state'),
      primary_topic: values.get('primary_topic'),
      search_intent: values.get('search_intent'),
      content_role: values.get('content_role'),
      family_id: values.get('family_id') === '' ? null : values.get('family_id'),
      claim_risk: values.get('claim_risk'),
      action: values.get('action'),
      priority: values.get('priority'),
      human_reviewed: values.get('human_reviewed') === 'on',
      approved: canApprove ? values.get('approved') === 'on' : Boolean(page.approved),
    });
  }
  return (
    <tr>
      <td>
        <form id={`page-${display(page.page_id)}`} onSubmit={(event) => void save(event)}>
          {firstNonEmpty(page.title, page.original_url)}
          <br />
          <small>{display(page.page_id)}</small>
        </form>
      </td>
      <td>
        <select
          form={`page-${display(page.page_id)}`}
          name="inclusion_state"
          defaultValue={display(page.inclusion_state)}
        >
          <option value="included">Included</option>
          <option value="excluded">Excluded</option>
          <option value="needs_review">Needs review</option>
        </select>
      </td>
      <td>
        <TextInput
          form={`page-${display(page.page_id)}`}
          name="primary_topic"
          defaultValue={display(page.primary_topic)}
          aria-label="Primary topic"
        />
      </td>
      <td>
        <select
          form={`page-${display(page.page_id)}`}
          name="search_intent"
          defaultValue={display(page.search_intent)}
        >
          <option value="unclassified">Unclassified</option>
          <option value="learn_condition">Learn condition</option>
          <option value="answer_specific_question">Specific question</option>
          <option value="find_local_provider">Find local provider</option>
        </select>
      </td>
      <td>
        <select
          form={`page-${display(page.page_id)}`}
          name="content_role"
          defaultValue={display(page.content_role)}
        >
          <option value="unclassified">Unclassified</option>
          <option value="primary_guide">Primary guide</option>
          <option value="supporting_article">Supporting</option>
          <option value="faq">FAQ</option>
          <option value="local_article">Local</option>
        </select>
      </td>
      <td>
        <select
          form={`page-${display(page.page_id)}`}
          name="family_id"
          defaultValue={display(page.family_id)}
        >
          <option value="">Unassigned</option>
          {families.map((item) => (
            <option key={display(item.family_id)} value={display(item.family_id)}>
              {display(item.name)}
            </option>
          ))}
        </select>
      </td>
      <td>
        <select
          form={`page-${display(page.page_id)}`}
          name="claim_risk"
          defaultValue={display(page.claim_risk)}
        >
          <option value="none">None</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="requires_professional_review">Professional review</option>
        </select>
      </td>
      <td>
        <select
          form={`page-${display(page.page_id)}`}
          name="action"
          defaultValue={display(page.action)}
        >
          <option value="undecided">Undecided</option>
          <option value="preserve">Preserve</option>
          <option value="refresh">Refresh</option>
          <option value="expand">Expand</option>
          <option value="consolidate">Consolidate</option>
          <option value="reposition">Reposition</option>
          <option value="claim_review">Claim review</option>
        </select>
        <select
          form={`page-${display(page.page_id)}`}
          name="priority"
          defaultValue={display(page.priority)}
        >
          <option value="priority_1">P1</option>
          <option value="priority_2">P2</option>
          <option value="priority_3">P3</option>
          <option value="later">Later</option>
        </select>
      </td>
      <td>
        <label>
          <input
            form={`page-${display(page.page_id)}`}
            type="checkbox"
            name="human_reviewed"
            defaultChecked={Boolean(page.human_reviewed)}
          />{' '}
          Reviewed
        </label>
        <label>
          <input
            form={`page-${display(page.page_id)}`}
            type="checkbox"
            name="approved"
            defaultChecked={Boolean(page.approved)}
            disabled={!canApprove}
          />{' '}
          Approved
        </label>
        <Button disabled={!canReview} form={`page-${display(page.page_id)}`}>
          Save
        </Button>
      </td>
    </tr>
  );
}

function display(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function firstNonEmpty(first: unknown, fallback: unknown): string {
  const value = display(first);
  return value.length > 0 ? value : display(fallback);
}
