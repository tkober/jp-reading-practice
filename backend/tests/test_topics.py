"""Topics: seeding from Markdown, customization surviving a reseed, and the
CRUD API (issue #8)."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Topic, get_sessionmaker, seed_topics
from app.topic_files import load_topic_files

EXPECTED_SLUGS = {
    "daily-life",
    "history",
    "current-events",
    "culture",
    "travel",
    "science",
    "short-story",
}


async def test_the_seven_built_in_topic_files_load() -> None:
    files = load_topic_files()
    assert {f.slug for f in files} == EXPECTED_SLUGS
    for f in files:
        assert f.title
        assert f.prompt
        assert f.default_style in ("casual", "polite", "formal")


async def test_startup_seeds_the_built_in_topics(session: AsyncSession) -> None:
    rows = list(await session.scalars(select(Topic)))
    assert {row.slug for row in rows} == EXPECTED_SLUGS
    for row in rows:
        assert row.is_builtin is True
        assert row.is_customized is False


async def test_reseeding_refreshes_an_untouched_built_in(session: AsyncSession) -> None:
    row = (await session.scalars(select(Topic).where(Topic.slug == "daily-life"))).one()
    await session.execute(
        Topic.__table__.update().where(Topic.id == row.id).values(title="Mutated")
    )
    await session.commit()

    await seed_topics(session)
    await session.commit()

    # The raw `Topic.__table__.update()` above and `seed_topics`'s own
    # INSERT .. ON CONFLICT bypass the ORM's session-synchronization, so
    # `session`'s identity map would otherwise still hand back the
    # pre-reseed object -- read back through a fresh session instead, the
    # same way a real request would.
    async with get_sessionmaker()() as fresh:
        refreshed = await fresh.get(Topic, row.id)
    assert refreshed is not None
    assert refreshed.title == "Daily life"


async def test_reseeding_keeps_a_customized_topics_wording(session: AsyncSession) -> None:
    row = (await session.scalars(select(Topic).where(Topic.slug == "history"))).one()
    await session.execute(
        Topic.__table__.update()
        .where(Topic.id == row.id)
        .values(title="My history", is_customized=True)
    )
    await session.commit()

    await seed_topics(session)
    await session.commit()

    async with get_sessionmaker()() as fresh:
        refreshed = await fresh.get(Topic, row.id)
    assert refreshed is not None
    assert refreshed.title == "My history"


# --- feed_urls (issue #15) ----------------------------------------------------


async def test_current_events_is_seeded_with_its_feed_url(session: AsyncSession) -> None:
    row = (await session.scalars(select(Topic).where(Topic.slug == "current-events"))).one()
    assert row.feed_urls == ["https://www.nhk.or.jp/rss/news/cat0.xml"]


async def test_reseeding_updates_an_untouched_built_ins_feed_url(session: AsyncSession) -> None:
    row = (await session.scalars(select(Topic).where(Topic.slug == "current-events"))).one()
    await session.execute(
        Topic.__table__.update()
        .where(Topic.id == row.id)
        .values(feed_urls=["https://www3.nhk.or.jp/rss/news/cat0.xml"])  # the old, frozen URL
    )
    await session.commit()

    await seed_topics(session)
    await session.commit()

    async with get_sessionmaker()() as fresh:
        refreshed = await fresh.get(Topic, row.id)
    assert refreshed is not None
    assert refreshed.feed_urls == ["https://www.nhk.or.jp/rss/news/cat0.xml"]


async def test_reseeding_keeps_a_customized_topics_feed_url(session: AsyncSession) -> None:
    row = (await session.scalars(select(Topic).where(Topic.slug == "current-events"))).one()
    await session.execute(
        Topic.__table__.update()
        .where(Topic.id == row.id)
        .values(feed_urls=["https://example.test/my-own-feed.xml"], is_customized=True)
    )
    await session.commit()

    await seed_topics(session)
    await session.commit()

    async with get_sessionmaker()() as fresh:
        refreshed = await fresh.get(Topic, row.id)
    assert refreshed is not None
    assert refreshed.feed_urls == ["https://example.test/my-own-feed.xml"]


# --- API ----------------------------------------------------------------------


async def test_list_topics_returns_the_seeded_builtins(client: AsyncClient) -> None:
    response = await client.get("/api/topics")
    assert response.status_code == 200
    body = response.json()
    assert {t["slug"] for t in body} == EXPECTED_SLUGS
    assert all(t["is_builtin"] for t in body)


async def test_get_topic_by_id(client: AsyncClient) -> None:
    topics = (await client.get("/api/topics")).json()
    first = topics[0]

    response = await client.get(f"/api/topics/{first['id']}")
    assert response.status_code == 200
    assert response.json()["slug"] == first["slug"]


async def test_get_unknown_topic_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/topics/999999")
    assert response.status_code == 404


async def test_create_topic_is_custom_and_customized(client: AsyncClient) -> None:
    response = await client.post(
        "/api/topics",
        json={
            "title": "My own topic",
            "glyph": "私",
            "prompt": "Write about something I like.",
            "default_style": "polite",
            "feed_urls": [],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["is_builtin"] is False
    assert body["is_customized"] is True
    assert body["slug"]  # derived from the title


async def test_update_topic_marks_it_customized(client: AsyncClient) -> None:
    topics = (await client.get("/api/topics")).json()
    daily_life = next(t for t in topics if t["slug"] == "daily-life")
    assert daily_life["is_customized"] is False

    response = await client.put(f"/api/topics/{daily_life['id']}", json={"title": "My day"})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "My day"
    assert body["is_customized"] is True


async def test_reset_restores_the_built_in_file_content(client: AsyncClient) -> None:
    topics = (await client.get("/api/topics")).json()
    daily_life = next(t for t in topics if t["slug"] == "daily-life")
    await client.put(f"/api/topics/{daily_life['id']}", json={"title": "Mutated"})

    response = await client.post(f"/api/topics/{daily_life['id']}/reset")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Daily life"
    assert body["is_customized"] is False


async def test_reset_a_custom_topic_is_rejected(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/api/topics",
            json={"title": "Custom", "prompt": "Something."},
        )
    ).json()

    response = await client.post(f"/api/topics/{created['id']}/reset")
    assert response.status_code == 400


async def test_delete_custom_topic_succeeds(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/api/topics",
            json={"title": "Temporary", "prompt": "Something."},
        )
    ).json()

    response = await client.delete(f"/api/topics/{created['id']}")
    assert response.status_code == 204

    assert (await client.get(f"/api/topics/{created['id']}")).status_code == 404


async def test_delete_builtin_topic_is_rejected(client: AsyncClient) -> None:
    topics = (await client.get("/api/topics")).json()
    daily_life = next(t for t in topics if t["slug"] == "daily-life")

    response = await client.delete(f"/api/topics/{daily_life['id']}")
    assert response.status_code == 400

    assert (await client.get(f"/api/topics/{daily_life['id']}")).status_code == 200
