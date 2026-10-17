import { Routes } from '@angular/router';

/**
 * Every screen and state from issue #6, for the owner to click through and
 * approve before #8+ build the real thing. Registered under `/preview`
 * only when `isDevMode()` (see `app.routes.ts`) so a production build never
 * ships these routes — the `npx ng build` check in the brief looks for
 * exactly that.
 */
export const previewRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./preview-index').then((m) => m.PreviewIndex),
    title: 'Design preview',
  },
  {
    path: 'setup',
    loadComponent: () => import('./screens/setup.preview').then((m) => m.SetupPreview),
    data: { variant: 'default' },
  },
  {
    path: 'setup-adjust',
    loadComponent: () => import('./screens/setup.preview').then((m) => m.SetupPreview),
    data: { variant: 'adjust' },
  },
  {
    path: 'setup-no-key',
    loadComponent: () => import('./screens/setup.preview').then((m) => m.SetupPreview),
    data: { variant: 'no-key' },
  },
  {
    path: 'setup-kt-offline',
    loadComponent: () => import('./screens/setup.preview').then((m) => m.SetupPreview),
    data: { variant: 'kt-offline' },
  },
  {
    path: 'generating',
    loadComponent: () => import('./screens/generating.preview').then((m) => m.GeneratingPreview),
  },
  {
    path: 'gate',
    loadComponent: () => import('./screens/gate.preview').then((m) => m.GatePreview),
  },
  {
    path: 'reading',
    loadComponent: () => import('./screens/reading.preview').then((m) => m.ReadingPreview),
    data: { variant: 'default' },
  },
  {
    path: 'reading-word',
    loadComponent: () => import('./screens/reading.preview').then((m) => m.ReadingPreview),
    data: { variant: 'word' },
  },
  {
    path: 'reading-answer',
    loadComponent: () => import('./screens/reading.preview').then((m) => m.ReadingPreview),
    data: { variant: 'answer' },
  },
  {
    path: 'reading-chat',
    loadComponent: () => import('./screens/reading.preview').then((m) => m.ReadingPreview),
    data: { variant: 'chat' },
  },
  {
    path: 'reading-chat-focus',
    loadComponent: () => import('./screens/reading.preview').then((m) => m.ReadingPreview),
    data: { variant: 'chat-focus' },
  },
  {
    path: 'reading-peek',
    loadComponent: () => import('./screens/reading.preview').then((m) => m.ReadingPreview),
    data: { variant: 'peek' },
  },
  {
    path: 'reading-paused',
    loadComponent: () => import('./screens/reading.preview').then((m) => m.ReadingPreview),
    data: { variant: 'paused' },
  },
  {
    path: 'questions',
    loadComponent: () => import('./screens/questions.preview').then((m) => m.QuestionsPreview),
    data: { variant: 'default' },
  },
  {
    path: 'questions-answered',
    loadComponent: () => import('./screens/questions.preview').then((m) => m.QuestionsPreview),
    data: { variant: 'answered' },
  },
  {
    path: 'summary',
    loadComponent: () => import('./screens/summary.preview').then((m) => m.SummaryPreview),
  },
  {
    path: 'history',
    loadComponent: () => import('./screens/history.preview').then((m) => m.HistoryPreview),
    data: { variant: 'default' },
  },
  {
    path: 'history-empty',
    loadComponent: () => import('./screens/history.preview').then((m) => m.HistoryPreview),
    data: { variant: 'empty' },
  },
  {
    path: 'stats',
    loadComponent: () => import('./screens/stats.preview').then((m) => m.StatsPreview),
    data: { variant: 'default' },
  },
  {
    path: 'stats-empty',
    loadComponent: () => import('./screens/stats.preview').then((m) => m.StatsPreview),
    data: { variant: 'empty' },
  },
  {
    path: 'topics',
    loadComponent: () => import('./screens/topics.preview').then((m) => m.TopicsPreview),
  },
  {
    path: 'topic-edit',
    loadComponent: () => import('./screens/topic-edit.preview').then((m) => m.TopicEditPreview),
  },
  {
    path: 'generation-failed',
    loadComponent: () =>
      import('./screens/generation-failed.preview').then((m) => m.GenerationFailedPreview),
  },
];
