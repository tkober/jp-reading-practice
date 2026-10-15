import { Routes } from '@angular/router';

export const routes: Routes = [
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
