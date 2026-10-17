export type {
  ReadingParagraph,
  ReadingWord,
  WordActivateEvent,
} from '../../../proto/tappable-ruby-text/tappable-ruby-text';
export type {
  WordActionKind,
  WordActionOption,
  WordAnchorRect,
  WordAnswer,
  WordDetails,
} from '../../../proto/word-popover-sheet/word-popover-sheet';
export type { ChatMessage } from '../../../proto/side-panel/side-panel';

import type { ReadingParagraph } from '../../../proto/tappable-ruby-text/tappable-ruby-text';

export interface ReadingTextData {
  titleJapanese: string;
  paragraphs: readonly ReadingParagraph[];
}
