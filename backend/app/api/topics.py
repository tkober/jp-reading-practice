"""Topics CRUD (issue #8) -- list, get, create, update, reset, delete.

Mirrors jp-conversation-practice's `api/scenarios.py` closely: editing marks
a row `is_customized` (which is what stops the next boot's `seed_topics`
from overwriting it), "reset" only works on a built-in and re-applies its
own Markdown file immediately rather than waiting for the next boot, and
delete is for custom topics only -- there is no file to restore a built-in
from if it were deletable, and deleting one would silently drop it from
`seed_topics`'s next run too.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Topic, get_session
from ..models import TopicCreate, TopicOut, TopicUpdate
from ..topic_files import load_topic_files

router = APIRouter()


def to_out(row: Topic) -> TopicOut:
    return TopicOut(
        id=row.id,
        slug=row.slug,
        title=row.title,
        glyph=row.glyph,
        prompt=row.prompt,
        default_style=row.default_style,  # type: ignore[arg-type]
        feed_urls=list(row.feed_urls or []),
        sort_order=row.sort_order,
        is_builtin=row.is_builtin,
        is_customized=row.is_customized,
    )


async def _get_or_404(session: AsyncSession, topic_id: int) -> Topic:
    row = await session.get(Topic, topic_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return row


@router.get("", response_model=list[TopicOut])
async def list_topics(session: AsyncSession = Depends(get_session)) -> list[TopicOut]:
    rows = await session.scalars(select(Topic).order_by(Topic.sort_order, Topic.title))
    return [to_out(row) for row in rows]


@router.get("/{topic_id}", response_model=TopicOut)
async def get_topic(topic_id: int, session: AsyncSession = Depends(get_session)) -> TopicOut:
    return to_out(await _get_or_404(session, topic_id))


@router.post("", response_model=TopicOut, status_code=201)
async def create_topic(
    payload: TopicCreate, session: AsyncSession = Depends(get_session)
) -> TopicOut:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title is required.")
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt is required.")

    # New topics sort after the built-in ones without renumbering them.
    highest = await session.scalar(select(func.max(Topic.sort_order)))
    row = Topic(
        slug=await _unique_slug(session, title),
        title=title,
        glyph=payload.glyph.strip(),
        prompt=prompt,
        default_style=payload.default_style,
        feed_urls=list(payload.feed_urls),
        is_builtin=False,
        is_customized=True,
        sort_order=(highest or 0) + 1,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return to_out(row)


@router.put("/{topic_id}", response_model=TopicOut)
async def update_topic(
    topic_id: int, payload: TopicUpdate, session: AsyncSession = Depends(get_session)
) -> TopicOut:
    """Edit a topic. Marks it `is_customized`, same as
    jp-conversation-practice's scenario `PUT` -- this is what stops the next
    boot from seeding the Markdown version back over the user's wording.
    """
    row = await _get_or_404(session, topic_id)
    provided = payload.model_dump(exclude_unset=True)

    values: dict[str, object] = {"is_customized": True, "updated_at": func.now()}
    for field in ("title", "glyph", "prompt"):
        if field in provided and provided[field] is not None:
            values[field] = str(provided[field]).strip()
    if "default_style" in provided and provided["default_style"] is not None:
        values["default_style"] = provided["default_style"]
    if "feed_urls" in provided and provided["feed_urls"] is not None:
        values["feed_urls"] = list(provided["feed_urls"])

    if "title" in values and not values["title"]:
        raise HTTPException(status_code=422, detail="Title is required.")
    if "prompt" in values and not values["prompt"]:
        raise HTTPException(status_code=422, detail="Prompt is required.")

    await session.execute(update(Topic).where(Topic.id == row.id).values(**values))
    await session.commit()
    return to_out(await _get_or_404(session, topic_id))


@router.post("/{topic_id}/reset", response_model=TopicOut)
async def reset_topic(topic_id: int, session: AsyncSession = Depends(get_session)) -> TopicOut:
    """Restore a built-in topic from its Markdown file right away.

    Clearing `is_customized` alone would be enough for the *next* boot's
    `seed_topics` to overwrite the row, but re-applying the file content now
    (same as `reset_scenario` in jp-conversation-practice) means the editor
    shows the restored text immediately instead of the stale one.
    """
    row = await _get_or_404(session, topic_id)
    if not row.is_builtin:
        raise HTTPException(status_code=400, detail="Only built-in topics can be reset.")

    original = next((f for f in load_topic_files() if f.slug == row.slug), None)
    if original is None:
        raise HTTPException(status_code=404, detail="No Markdown file exists for this topic.")

    await session.execute(
        update(Topic)
        .where(Topic.id == row.id)
        .values(
            title=original.title,
            glyph=original.glyph,
            prompt=original.prompt,
            default_style=original.default_style,
            feed_urls=list(original.feed_urls),
            is_customized=False,
            updated_at=func.now(),
        )
    )
    await session.commit()
    return to_out(await _get_or_404(session, topic_id))


@router.delete("/{topic_id}", status_code=204)
async def delete_topic(topic_id: int, session: AsyncSession = Depends(get_session)) -> None:
    """Remove a custom topic. Built-ins cannot be deleted -- `reset` is
    their equivalent, and `seed_topics` would simply bring a deleted
    built-in back on the next boot anyway.

    Past texts keep their own `params.topic_slug`/title, and `topic_id`
    falls back to NULL (`ON DELETE SET NULL`) -- they stay self-describing.
    """
    row = await _get_or_404(session, topic_id)
    if row.is_builtin:
        raise HTTPException(status_code=400, detail="Built-in topics cannot be deleted.")
    await session.execute(delete(Topic).where(Topic.id == topic_id))
    await session.commit()


async def _unique_slug(session: AsyncSession, title: str) -> str:
    """Derive a URL-safe slug from the title, suffixed until it is free."""
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "topic"
    candidate = base
    suffix = 2
    while await session.scalar(select(Topic.id).where(Topic.slug == candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate
