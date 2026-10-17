"""Loading the built-in topics from Markdown files.

Topics ship as Markdown with YAML front matter, same convention as
jp-conversation-practice's scenarios (``scenario_files.py``) -- editable,
reviewable and diffable as prose rather than buried in a Python list:

    ---
    slug: daily-life
    title: Daily life
    glyph: 日常
    default_style: casual
    sort_order: 0
    feed_urls: []
    ---

    Write about an ordinary day: ...

The body is the model-facing topic prompt and is therefore English, like
``title``. ``glyph`` is Japanese (shown on the topic tile). They are the
*initial* content only: once seeded, the database is the source of truth,
and the Topics list/editor work against that (``app/db.py``'s
``seed_topics``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from .config import get_settings

log = logging.getLogger(__name__)

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VALID_STYLES = ("casual", "polite", "formal")
DEFAULT_STYLE = "casual"


@dataclass(frozen=True)
class TopicFile:
    slug: str
    title: str
    glyph: str
    prompt: str
    default_style: str = DEFAULT_STYLE
    feed_urls: list[str] = field(default_factory=list)


def topics_dir() -> Path:
    """Where the Markdown topics live (overridable for the container)."""
    configured = get_settings().topics_dir
    path = Path(configured)
    if path.is_absolute():
        return path
    # Relative paths resolve against the backend package's parent, so running
    # from backend/ and from / (the image's workdir) both work.
    return Path(__file__).resolve().parent.parent / path


def _parse_feed_urls(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(url).strip() for url in raw if str(url).strip()]


def load_topic_files() -> list[TopicFile]:
    """Parse every ``*.md`` in the topics directory, sorted by filename.

    Filenames carry a numeric prefix (``01-daily-life.md``) purely to fix the
    order in the picker; the slug and the actual `sort_order` come from the
    front matter.

    A malformed file is skipped with a log line rather than raising: one bad
    file must not stop the app from booting.
    """
    directory = topics_dir()
    if not directory.is_dir():
        log.warning("Topics directory %s does not exist", directory)
        return []

    by_slug: dict[str, tuple[int, TopicFile]] = {}

    for path in sorted(directory.glob("*.md")):
        try:
            parsed = frontmatter.load(path)
        except Exception as exc:  # noqa: BLE001 - malformed YAML raises broadly
            log.warning("Skipping topic %s: %s", path.name, exc)
            continue

        slug = str(parsed.get("slug") or path.stem.split("-", 1)[-1]).strip()
        title = str(parsed.get("title") or "").strip()
        glyph = str(parsed.get("glyph") or "").strip()
        prompt = parsed.content.strip()
        default_style = str(parsed.get("default_style") or DEFAULT_STYLE).strip().lower()
        sort_order = parsed.get("sort_order")
        feed_urls = _parse_feed_urls(parsed.get("feed_urls"))

        if not SLUG_PATTERN.match(slug):
            log.warning("Skipping topic %s: invalid slug %r", path.name, slug)
            continue
        if not title or not prompt:
            log.warning("Skipping topic %s: title and body are required", path.name)
            continue
        if default_style not in VALID_STYLES:
            log.warning(
                "Skipping topic %s: invalid default_style %r", path.name, default_style
            )
            continue
        if slug in by_slug:
            log.warning("Skipping topic %s: duplicate slug %r", path.name, slug)
            continue

        order = int(sort_order) if isinstance(sort_order, int) else len(by_slug)
        by_slug[slug] = (
            order,
            TopicFile(
                slug=slug,
                title=title,
                glyph=glyph,
                prompt=prompt,
                default_style=default_style,
                feed_urls=feed_urls,
            ),
        )

    return [entry for _, entry in sorted(by_slug.values(), key=lambda pair: pair[0])]
