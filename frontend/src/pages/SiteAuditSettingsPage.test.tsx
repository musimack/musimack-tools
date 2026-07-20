import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { siteAuditSettingsApi } from '../site-audit-settings/api';
import type { GlobalSettings, Preset, ProfilePage } from '../site-audit-settings/contracts';
import { SiteAuditSettingsPage } from './SiteAuditSettingsPage';

vi.mock('../auth/AuthContext', () => ({ useAuth: vi.fn() }));
vi.mock('../site-audit-settings/api', () => ({
  siteAuditSettingsApi: {
    settings: vi.fn(),
    updateSettings: vi.fn(),
    presets: vi.fn(),
    profiles: vi.fn(),
    createProfile: vi.fn(),
    updateProfile: vi.fn(),
    disableProfile: vi.fn(),
    archiveProfile: vi.fn(),
    effectiveSettings: vi.fn(),
    testRules: vi.fn(),
  },
}));

const wordpress: Preset = {
  preset_id: 'wordpress',
  version: 'wordpress-1',
  label: 'WordPress',
  explanation: 'Visible WordPress URL governance suggestions.',
  tracking_parameters: [
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_term',
    'utm_content',
    'gclid',
    'fbclid',
    'msclkid',
  ],
  acceptance_required: true,
  rules: [
    {
      rule_id: 'wordpress.wp_json',
      name: 'Exclude WordPress REST API',
      description: 'Optional',
      enabled: false,
      match_type: 'path_starts_with',
      match_value: '/wp-json/',
      case_sensitive: true,
      action: 'exclude_from_discovery',
      reason: 'Optional API path',
      reason_code: 'wordpress_wp_json',
      priority: 100,
      overrides_rule_ids: [],
    },
    {
      rule_id: 'wordpress.pagination.sitemap_review',
      name: 'Review pagination for sitemap eligibility',
      description: 'Pagination remains metadata eligible',
      enabled: true,
      match_type: 'query_parameter_exists',
      match_value: 'page',
      case_sensitive: true,
      action: 'crawl_and_mark_for_review',
      reason: 'Review pagination',
      reason_code: 'wordpress_pagination_sitemap_review',
      priority: 100,
      overrides_rule_ids: [],
    },
  ],
};

const profiles: ProfilePage = {
  items: [
    {
      profile_id: 'profile-safe-1',
      site_label: 'Example Store',
      authorized_seed: 'https://www.example.com/',
      seed_host: 'www.example.com',
      state: 'enabled',
      current_version: 2,
      updated_at: '2026-07-20T00:00:00Z',
      configuration: {
        site_label: 'Example Store',
        authorized_seed: 'https://www.example.com/',
        approved_hosts: ['www.example.com'],
        preset_id: 'wordpress',
        preset_version: 'wordpress-1',
        preset_accepted: true,
        preset_rule_states: {},
        tracking_parameters_accepted: true,
        tracking_parameter_exceptions: [],
        rules: [],
        crawl_profile: 'standard_crawl',
        crawl_limit_overrides: {},
        metadata_thresholds: {},
        enabled_modules: { images: true, structured_data: true },
        business_importance: [],
      },
    },
  ],
  offset: 0,
  limit: 500,
  total: 1,
  ordering: 'site_label_asc_profile_id_asc-v1',
};

const settings: GlobalSettings = {
  version: 1,
  configuration: {
    default_crawl_profile: 'standard_crawl',
    default_platform_preset: null,
    default_tracking_parameters: wordpress.tracking_parameters,
    default_url_rules: [],
    metadata_thresholds: {
      title_minimum: 30,
      title_maximum: 60,
      description_minimum: 70,
      description_maximum: 160,
    },
    default_report_page_size: 50,
    sitemap_policy: { pagination: 'review' },
    specialist_summaries: { images: true, structured_data: true },
    maximum_retained_urls: 100000,
    maximum_export_rows: 100000,
  },
  configuration_hash: 'a'.repeat(64),
  created_by: 'administrator-1',
  created_at: '2026-07-20T00:00:00Z',
};

const api = vi.mocked(siteAuditSettingsApi);
const auth = vi.mocked(useAuth);

function prepare(administrator: boolean) {
  auth.mockReturnValue({
    can: (permission: string) => permission === 'settings.manage' && administrator,
  } as ReturnType<typeof useAuth>);
  api.presets.mockResolvedValue([wordpress]);
  api.profiles.mockResolvedValue(profiles);
  api.settings.mockResolvedValue(settings);
  api.effectiveSettings.mockResolvedValue({
    preset: wordpress,
    preset_accepted: true,
    site_profile: null,
    effective_rules: wordpress.rules,
    disabled_inherited_rules: [],
    warnings: [],
    tracking_parameters: wordpress.tracking_parameters,
    tracking_parameters_accepted: true,
    bounds: { sample_url_maximum: 100 },
  });
  api.testRules.mockResolvedValue({
    effective_settings: awaitEffective(),
    test: {
      results: [
        {
          original_url: 'https://example.com/private/page',
          normalized_url: 'https://example.com/private/page',
          matched: true,
          primary_rule: 'audit.sample_rule',
          conflict: false,
        },
      ],
      result_count: 1,
      network_access: false,
      discoveries_created: false,
    },
  });
}

function awaitEffective() {
  return {
    preset: wordpress,
    preset_accepted: true,
    site_profile: null,
    effective_rules: wordpress.rules,
    disabled_inherited_rules: [],
    warnings: [],
    tracking_parameters: wordpress.tracking_parameters,
    tracking_parameters_accepted: true,
    bounds: { sample_url_maximum: 100 },
  };
}

function renderPage(path = '/settings') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SiteAuditSettingsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

test('operator reviews and explicitly accepts a versioned preset without save controls', async () => {
  prepare(false);
  const user = userEvent.setup();
  renderPage();
  expect(await screen.findByRole('heading', { name: 'Site Audit Settings' })).toBeInTheDocument();
  expect(api.settings).not.toHaveBeenCalled();
  expect(api.profiles).toHaveBeenCalledWith(false);
  expect(screen.queryByRole('heading', { name: 'Global defaults' })).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Saved site profiles' })).not.toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText('Platform preset'), 'wordpress');
  expect(screen.getByText(wordpress.tracking_parameters.join(', '))).toBeInTheDocument();
  const optional = screen.getByRole('checkbox', { name: /Exclude WordPress REST API/u });
  expect(optional).toBeDisabled();
  await user.click(screen.getByRole('checkbox', { name: /Explicitly accept WordPress/u }));
  expect(optional).toBeEnabled();
  expect(optional).not.toBeChecked();
  expect(screen.getByText(/Review pagination for sitemap eligibility/u)).toBeInTheDocument();
});

test('operator resolves and tests the same bounded stateless request without network or discoveries', async () => {
  prepare(false);
  const user = userEvent.setup();
  renderPage('/settings?preset=wordpress');
  await screen.findByRole('heading', { name: 'URL rule tester' });
  await user.click(screen.getByRole('checkbox', { name: /Explicitly accept WordPress/u }));
  await user.click(screen.getByRole('checkbox', { name: /Strip the exact reviewed/u }));
  await user.click(screen.getByRole('button', { name: 'Resolve effective settings' }));
  await waitFor(() => {
    expect(api.effectiveSettings).toHaveBeenCalledTimes(1);
  });
  await user.clear(screen.getByLabelText(/Sample URLs/u));
  await user.type(screen.getByLabelText(/Sample URLs/u), 'https://example.com/private/page');
  await user.click(screen.getByRole('button', { name: 'Test sample URLs' }));
  await waitFor(() => {
    expect(api.testRules).toHaveBeenCalledTimes(1);
  });
  const request = api.testRules.mock.calls[0]?.[0];
  expect(request).toMatchObject({
    preset_id: 'wordpress',
    preset_version: 'wordpress-1',
    preset_accepted: true,
    tracking_parameters_accepted: true,
  });
  expect(
    within(screen.getByRole('heading', { name: 'Sample URL matches' }).parentElement!).getByText(
      /network access: no/u,
    ),
  ).toBeInTheDocument();
});

test('administrator can edit versioned global settings and receives an unsaved warning', async () => {
  prepare(true);
  api.updateSettings.mockResolvedValue({ ...settings, version: 2 });
  const user = userEvent.setup();
  renderPage();
  expect(await screen.findByRole('heading', { name: 'Global defaults' })).toBeInTheDocument();
  expect(api.profiles).toHaveBeenCalledWith(true);
  await user.selectOptions(screen.getByLabelText('Default report page size'), '100');
  expect(screen.getByText('You have unsaved administrator changes.')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Save global defaults' }));
  await waitFor(() => {
    expect(api.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ default_report_page_size: 100 }),
      1,
    );
  });
});

test('administrator sees human labels before technical profile IDs and keyboard actions', async () => {
  prepare(true);
  renderPage();
  const heading = await screen.findByRole('heading', { name: 'Saved site profiles' });
  const card = heading.parentElement!;
  expect(within(card).getAllByText('Example Store').length).toBeGreaterThan(0);
  expect(within(card).getByText('profile-safe-1')).toHaveClass('secondary-id');
  expect(within(card).getByRole('button', { name: 'Edit' })).toBeEnabled();
  expect(within(card).getByRole('button', { name: 'Disable' })).toBeEnabled();
  expect(within(card).getByRole('button', { name: 'Archive' })).toBeEnabled();
});

test('administrator edits a new profile version and can disable it', async () => {
  prepare(true);
  api.updateProfile.mockResolvedValue({ ...profiles.items[0]!, site_label: 'Updated Store' });
  api.disableProfile.mockResolvedValue({
    ...profiles.items[0]!,
    state: 'disabled',
  });
  const user = userEvent.setup();
  renderPage();
  await user.click(await screen.findByRole('button', { name: 'Edit' }));
  const label = screen.getByLabelText('Site label');
  await user.clear(label);
  await user.type(label, 'Updated Store');
  await user.click(screen.getByRole('button', { name: 'Save new profile version' }));
  await waitFor(() => {
    expect(api.updateProfile).toHaveBeenCalledWith(
      'profile-safe-1',
      expect.objectContaining({ site_label: 'Updated Store' }),
      2,
    );
  });
  await user.click(screen.getByRole('button', { name: 'Disable' }));
  await waitFor(() => {
    expect(api.disableProfile).toHaveBeenCalledWith('profile-safe-1');
  });
});

test('broad-rule warning and explicit inherited disable reset with temporary overrides', async () => {
  prepare(false);
  const user = userEvent.setup();
  renderPage();
  await screen.findByRole('heading', { name: 'URL rule tester' });
  await user.selectOptions(screen.getByLabelText('Match type'), 'path_contains');
  await user.clear(screen.getByLabelText('Match value'));
  await user.type(screen.getByLabelText('Match value'), '/');
  expect(screen.getByText(/broad path-contains rule/u)).toBeInTheDocument();
  await user.type(screen.getByLabelText(/Disabled inherited rule IDs/u), 'wordpress.admin');
  await user.click(screen.getByRole('button', { name: 'Test sample URLs' }));
  await waitFor(() => {
    expect(api.testRules).toHaveBeenCalledTimes(1);
  });
  expect(api.testRules.mock.calls[0]?.[0].overrides).toMatchObject({
    disabled_rule_ids: ['wordpress.admin'],
  });
  await user.click(screen.getByRole('button', { name: 'Reset temporary overrides' }));
  expect(screen.getByLabelText(/Disabled inherited rule IDs/u)).toHaveValue('');
  expect(screen.queryByText(/broad path-contains rule/u)).not.toBeInTheDocument();
});

test('shows a bounded safe error state when settings loading fails', async () => {
  prepare(false);
  api.presets.mockRejectedValue(new Error('private database details'));
  renderPage();
  expect(
    await screen.findByRole('heading', { name: 'Site Audit Settings are unavailable' }),
  ).toBeInTheDocument();
  expect(screen.queryByText('private database details')).not.toBeInTheDocument();
});
