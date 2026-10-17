import { isDevMode } from '@angular/core';
import { Routes } from '@angular/router';

/**
 * `/preview` (issue #6): every screen and state built against the real
 * components with fixture data, for the owner to approve before #8+ wire
 * them up for real. Registered only in dev mode, per the brief -- a
 * production build's router config never has this route, so there is no
 * way to navigate there once deployed, even though the lazy chunk itself
 * (unreached, like any other lazy route) still exists in `dist/`.
 */
const previewRoute = isDevMode()
  ? [
      {
        path: 'preview',
        loadChildren: () => import('./preview/preview.routes').then((m) => m.previewRoutes),
      },
    ]
  : [];

export const routes: Routes = [
  ...previewRoute,
  { path: '', redirectTo: 'read', pathMatch: 'full' },
  {
    path: 'read',
    loadComponent: () => import('./pages/read/read').then((m) => m.ReadPage),
    title: 'Read · JP Reading Practice',
  },
  {
    path: 'history',
    loadComponent: () => import('./pages/history/history').then((m) => m.HistoryPage),
    title: 'History · JP Reading Practice',
  },
  {
    path: 'stats',
    loadComponent: () => import('./pages/stats/stats').then((m) => m.StatsPage),
    title: 'Stats · JP Reading Practice',
  },
  {
    path: 'topics',
    loadComponent: () => import('./pages/topics/topics').then((m) => m.TopicsPage),
    title: 'Topics · JP Reading Practice',
  },
  {
    path: 'settings',
    loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage),
    title: 'Settings · JP Reading Practice',
  },
  { path: '**', redirectTo: 'read' },
];
