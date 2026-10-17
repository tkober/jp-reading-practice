import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { SumiCard, SumiPage } from 'sumi-ui/layout';

interface PreviewLink {
  path: string;
  label: string;
  /** Shown as a small note under the link — for a state this page cannot
   *  itself demonstrate (e.g. a gesture-driven one, see "Reading — reading
   *  peek" below). */
  note?: string;
}

interface PreviewGroup {
  title: string;
  links: PreviewLink[];
}

const GROUPS: readonly PreviewGroup[] = [
  {
    title: '1. Setup',
    links: [
      { path: 'setup', label: 'Setup' },
      { path: 'setup-adjust', label: 'Setup — Adjust open' },
      { path: 'setup-no-key', label: 'Setup — no OpenAI key' },
      { path: 'setup-kt-offline', label: 'Setup — Kanji Trainer offline' },
    ],
  },
  { title: '2. Generating', links: [{ path: 'generating', label: 'Generating' }] },
  { title: '3. Reading gate', links: [{ path: 'gate', label: 'Gate' }] },
  {
    title: '4. Reading',
    links: [
      { path: 'reading', label: 'Reading' },
      { path: 'reading-word', label: 'Reading — word popover/sheet' },
      { path: 'reading-answer', label: 'Reading — word answer' },
      { path: 'reading-chat', label: 'Reading — chat panel' },
      {
        path: 'reading-peek',
        label: 'Reading — reading peek',
        note:
          'Shows 旅行 mid-peek, forced for this static page. For real: hover a known ' +
          'word ~500ms (desktop) or long-press it ~400ms (phone) to see its reading; ' +
          'moving away cancels it, a short tap opens the word lookup instead.',
      },
      { path: 'reading-paused', label: 'Reading — paused (blurred)' },
    ],
  },
  {
    title: '5. Questions',
    links: [
      { path: 'questions', label: 'Questions' },
      { path: 'questions-answered', label: 'Questions — answered' },
    ],
  },
  { title: '6. Summary', links: [{ path: 'summary', label: 'Summary' }] },
  {
    title: '7. History',
    links: [
      { path: 'history', label: 'History' },
      { path: 'history-empty', label: 'History — empty' },
    ],
  },
  {
    title: '8. Stats',
    links: [
      { path: 'stats', label: 'Stats' },
      { path: 'stats-empty', label: 'Stats — empty (<3 sessions)' },
    ],
  },
  {
    title: '9. Topics',
    links: [
      { path: 'topics', label: 'Topics' },
      { path: 'topic-edit', label: 'Topic editor' },
    ],
  },
  { title: '11. Error', links: [{ path: 'generation-failed', label: 'Generation failed' }] },
];

@Component({
  selector: 'preview-index',
  templateUrl: './preview-index.html',
  styleUrl: './preview-index.scss',
  imports: [RouterLink, SumiPage, SumiCard],
})
export class PreviewIndex {
  protected readonly groups = GROUPS;
}
