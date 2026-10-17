// Preview-only fixture data — not the learner's own data.
import type {
  WordAnswer,
  WordDetails,
} from '../../proto/word-popover-sheet/word-popover-sheet';
import type { ChatMessage } from '../../proto/side-panel/side-panel';
import { findWordByText } from './reading-text.fixture';

const WORD_ACTIONS = [
  { kind: 'explain', label: 'Explain word', weight: 2 },
  { kind: 'translate', label: 'Translate sentence', weight: 3 },
  { kind: 'grammar', label: 'Explain grammar', weight: 3 },
  { kind: 'tutor', label: 'Ask tutor', weight: 3 },
] as const;

/** A plain word lookup — 濡れても (the real token tapped in
 *  `READING_TEXT`), a kanji word with a dictionary meaning and a Kanji
 *  Trainer status, not a grammar pattern. */
export const WORD_DETAILS_PRIMARY: WordDetails = {
  word: findWordByText('濡れても').text,
  reading: 'ぬれても',
  meanings: ['to get wet (te-form of 濡れる + "even if")'],
  knownStatus: 'Kanji Trainer: Guru II',
  actions: WORD_ACTIONS,
};

/** A grammar-pattern lookup, anchored to the token that actually contains
 *  it (気にしないことにしました) — the popover names the pattern itself
 *  (〜ことにした), not the whole conjugated phrase, and shows a "Grammar"
 *  badge instead of a Kanji Trainer status (grammar patterns have none). */
export const WORD_DETAILS_GRAMMAR: WordDetails = {
  word: 'ことにした',
  meanings: ['decided to (do something)'],
  actions: WORD_ACTIONS,
  kind: 'grammar',
};

export const GRAMMAR_ANCHOR_WORD = findWordByText('気にしないことにしました。');

export const WORD_ANSWER_GRAMMAR: WordAnswer = {
  kind: 'grammar',
  text:
    '〜ことにした means "decided to ...". It marks a decision the speaker made themselves, ' +
    'as opposed to 〜ことになった, which marks something that was decided for them (by ' +
    'circumstances or someone else). Here: "I decided not to mind getting wet."',
};

export const CHAT_MESSAGES: readonly ChatMessage[] = [
  { role: 'user', text: 'なぜ雨なのに兼六園を楽しめたんですか？' },
  {
    role: 'assistant',
    text: '雨で人が少なかったので、ゆっくり歩くことができたからです。木の葉に落ちる雨の音も、静かで気持ちが良かったと書かれています。',
  },
  { role: 'user', text: 'この文の「濡れても気にしない」はどういう意味ですか？' },
  {
    role: 'assistant',
    text: '「〜ても気にしない」は「〜しても構わない、問題ない」という意味です。つまり、雨で服が濡れても、それを問題だと思わなかった、ということです。',
  },
];
