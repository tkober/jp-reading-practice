import type { TextSourceApi } from '../../core/api.types';
import type { SourceLine } from '../../features/read/reading/reading.types';

/**
 * "Source: <title> ↗" (issue #15) -- the one line shown under a
 * news-backed text's last paragraph (before "Done reading") and again on
 * its summary. `null` when the text has no source at all: not a
 * news-backed topic, or its material fetch failed (`material_error`
 * covers that case instead, as a gate notice).
 */
export function sourceLineFor(source: TextSourceApi | null): SourceLine | null {
  const title = source?.title.trim();
  const link = source?.link.trim();
  if (!title || !link) {
    return null;
  }
  return { label: `Source: ${title} ↗`, link };
}
