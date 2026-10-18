import { describe, expect, it } from 'vitest';
import { sourceLineFor } from './source-line';

describe('sourceLineFor', () => {
  it('is null when the text has no source', () => {
    expect(sourceLineFor(null)).toBeNull();
  });

  it('formats a label with the title and a trailing arrow, and keeps the link', () => {
    const line = sourceLineFor({
      title: '台風30号が沖縄に接近',
      link: 'https://news.web.nhk/newsweb/na/nd-20261018de61065',
      published: '2026-10-18T10:52:00+09:00',
      via: 'rss',
    });
    expect(line).toEqual({
      label: 'Source: 台風30号が沖縄に接近 ↗',
      link: 'https://news.web.nhk/newsweb/na/nd-20261018de61065',
    });
  });

  it('is null when the title is blank even if a link is present', () => {
    expect(
      sourceLineFor({
        title: '  ',
        link: 'https://example.com',
        published: null,
        via: 'web_search',
      }),
    ).toBeNull();
  });

  it('is null when the link is blank even if a title is present', () => {
    expect(sourceLineFor({ title: 'Title', link: '  ', published: null, via: 'rss' })).toBeNull();
  });
});
