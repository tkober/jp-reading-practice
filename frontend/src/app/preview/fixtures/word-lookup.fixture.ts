// Preview-only fixture data — not the learner's own data.
import type {
  WordAnswer,
  WordDetails,
} from '../../proto/word-popover-sheet/word-popover-sheet';
import type { ChatMessage } from '../../proto/side-panel/side-panel';

export const WORD_DETAILS_KENROKUEN: WordDetails = {
  word: '兼六園',
  reading: 'けんろくえん',
  meanings: ['Kenrokuen (a famous garden in Kanazawa)'],
  knownStatus: 'Not in Kanji Trainer',
  actions: [
    { kind: 'explain', label: 'Explain word', weight: 2 },
    { kind: 'translate', label: 'Translate sentence', weight: 3 },
    { kind: 'grammar', label: 'Explain grammar', weight: 3 },
    { kind: 'tutor', label: 'Ask tutor', weight: 3 },
  ],
};

export const WORD_DETAILS_KOTO: WordDetails = {
  word: 'ことにした',
  reading: 'ことにした',
  jlptLevel: 'N3',
  meanings: ['decided to (do something)'],
  knownStatus: 'Kanji Trainer: Guru II',
  actions: [
    { kind: 'explain', label: 'Explain word', weight: 2 },
    { kind: 'translate', label: 'Translate sentence', weight: 3 },
    { kind: 'grammar', label: 'Explain grammar', weight: 3 },
    { kind: 'tutor', label: 'Ask tutor', weight: 3 },
  ],
};

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
