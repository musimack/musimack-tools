import type { ComponentType } from 'react';
import type { Permission } from '../auth/contracts';
import {
  ArtifactsPage,
  HistoryPage,
  JobsPage,
  OverviewPage,
  SettingsPage,
  UsersPage,
} from '../pages/WorkspacePages';

export type WorkspaceRoute = {
  path: string;
  label: string;
  description: string;
  permission: Permission;
  component: ComponentType;
};

export const workspaceRoutes: readonly WorkspaceRoute[] = [
  {
    path: '/',
    label: 'Overview',
    description: 'Operational health at a glance',
    permission: 'diagnostics.view',
    component: OverviewPage,
  },
  {
    path: '/jobs',
    label: 'Jobs',
    description: 'Prepare and monitor toolkit work',
    permission: 'jobs.view',
    component: JobsPage,
  },
  {
    path: '/history',
    label: 'History',
    description: 'Review durable jobs and runs',
    permission: 'history.view',
    component: HistoryPage,
  },
  {
    path: '/artifacts',
    label: 'Artifacts',
    description: 'Find retained output files',
    permission: 'artifacts.view',
    component: ArtifactsPage,
  },
  {
    path: '/users',
    label: 'Users',
    description: 'Manage internal access',
    permission: 'users.view',
    component: UsersPage,
  },
  {
    path: '/settings',
    label: 'Settings',
    description: 'Inspect toolkit configuration',
    permission: 'settings.view',
    component: SettingsPage,
  },
] as const;
