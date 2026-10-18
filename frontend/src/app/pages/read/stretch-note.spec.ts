import { describe, expect, it } from 'vitest';
import { stretchNoteText } from './stretch-note';

describe('stretchNoteText', () => {
  it('reads "harder" as a little harder', () => {
    expect(stretchNoteText('harder')).toBe('Stretch is now a little harder.');
  });

  it('reads "easier" as a little easier', () => {
    expect(stretchNoteText('easier')).toBe('Stretch is now a little easier.');
  });

  it('is null otherwise', () => {
    expect(stretchNoteText(null)).toBeNull();
  });
});
