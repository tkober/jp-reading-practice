# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## What this is for

A Japanese reading practice app: generates reading texts at the learner's
level, using what the other apps in the suite -- chiefly
[kanji-trainer](https://github.com/tkober/kanji-trainer) -- already know
about their vocabulary. See `REQUIREMENTS.md` for the full concept (epic #1)
and the open questions that are not decided yet.

This repository currently holds only the backend skeleton (issue #2): no
domain logic, no frontend, no deployment. Everything below describes what
actually exists; do not take it as a preview of what #3/#4 and later issues
will add.

## Language convention

Conversation with the user happens in **German**. Everything in the
repository -- identifiers, comments, commit messages, documentation and every
string a learner would read -- is **English**, the same convention the other
apps in the suite use.

## Working in this repository

Every change goes on a feature branch and reaches `main` through a pull
request. Do not merge locally and push `main` -- a branch that is already an
ancestor of `main` cannot be turned into a PR afterwards, and the review
never happens.

```bash
git checkout -b feature/<topic>
# ... commit ...
git push -u origin feature/<topic>
# then open a PR against main and leave the merge to the repository owner
```

## Commands

```bash
cd backend
uv sync                     # install
uv run uvicorn app.main:app --reload --port 8000
uv run pytest                               # needs Docker: testcontainers starts a Postgres
TEST_DB_URL=postgresql://dev@localhost:5432/postgres uv run pytest   # against a local superuser connection, no Docker
uv run alembic revision --autogenerate -m "..."   # after changing a model in db.py
uv run alembic upgrade head                       # apply migrations by hand, outside init_db
```

There is no frontend yet (issue #3).

## Persistence

Postgres only -- no SQLite variant, unlike kanji-trainer and
jp-conversation-practice; that was a deliberate decision for this app (see
issue #2). The same two-role split as the other stacks: an **owner** role
runs DDL in `init_db()` at startup, an **app** role serves every request. The
app role's access comes from server-side `ALTER DEFAULT PRIVILEGES`
(`dev/initdb/01-roles.sql` locally; the deployment bootstrap SQL that issue #4
adds is expected to reuse it), so no GRANT is issued from code.

Schema changes are Alembic revisions (`backend/alembic/versions/`), applied by
`init_db()` on every startup via `upgrade head`. To change the schema: edit
the model in `db.py`, then `cd backend && uv run alembic revision
--autogenerate -m "..."` and hand-check the result. `env.py` runs either on
the owner connection `init_db` already opened
(`config.attributes["connection"]`, inside its transaction) or, from the CLI,
on an engine it builds itself from the owner URL;
`target_metadata = Base.metadata` is what makes `--autogenerate` and the
`compare_metadata` guard in `tests/test_migrations.py` possible -- a model
change that ships without a matching revision fails that test.

Unlike kanji-trainer, there is no pre-Alembic bridge
(`migrate_schema()`/`ADDED_COLUMNS`): this app starts from nothing, so every
database reaches the schema by running the Alembic revisions from scratch.
Add that bridge back only if a release ever ships a schema change outside
Alembic, which has not happened here.

`RuntimeConfig` (`runtime_config.py`) is what request paths take, not raw
settings: environment defaults with the `app_settings` row layered on top. A
NULL column means "not set here", so clearing a field in the Settings UI
falls back to the environment rather than blanking it. It is loaded per
request -- the table has one row, and a stale OpenAI key after a settings
change would be worse than the lookup.

The OpenAI API key never leaves the backend: `/api/settings` returns only
whether one is set, a four-character hint, and whether it came from the
environment (which the UI needs in order to explain why an env key cannot be
cleared from the browser). `model_catalog.py` builds the Settings screen's
model dropdowns the same way jp-conversation-practice's does, reduced to the
two chat slots this app has (`generation`, `help`): curated entries plus
whatever the account's `GET /v1/models` adds, with no pricing yet.

Tests run against a throwaway Postgres, reproducing the owner/app split, so a
stray DDL statement in a request path fails there rather than at deploy time.
Without Docker, `TEST_DB_URL` points `conftest.py` at a local superuser
connection instead of testcontainers; either way it creates and drops the
roles and the database itself, exactly like the deployment bootstrap would.
The test roles are named `jp_reading_practice_test_*`, never the app's own:
the local Postgres usually holds the dev database too, and the teardown drops
the roles it created.
HTTP tests use `httpx.ASGITransport` rather than `TestClient`: the latter runs
the app on its own event loop in a worker thread, which the shared SQLAlchemy
engine cannot be used from.

## Kanji Trainer (MCP)

`app/kanji_trainer.py` (issue #5) is the client for kanji-trainer's own
read-only MCP server at `/mcp` (Streamable HTTP, stateless, JSON responses --
see its `app/mcp_server.py` and CLAUDE.md "MCP server" section). One function
per tool (`get_known_kanji`, `get_known_vocabulary`, `get_learning_summary`,
`lookup_items`, `get_jlpt_levels`), returning Pydantic models that mirror the
server's own -- there is no shared package between the two repos, so keep
them in sync by hand when that server's shapes change. Built on the `mcp`
SDK's `ClientSession` + `mcp.client.streamable_http`, pinned `mcp>=1.30,<2`
like the server (2.x renamed the API). A fresh connection per call, since the
server is stateless and reused across many short-lived requests -- nothing
here is worth keeping a persistent session open for.

Every failure -- unreachable, a 421 (kanji-trainer's own `MCP_ALLOWED_HOSTS`
rejecting this host), a tool-side error, a timeout -- becomes one
`KanjiTrainerUnavailable` with an English, human-readable message. Nothing in
this module decides how to degrade; that is left to the caller.

Caching is in-process: `get_known_kanji`/`get_known_vocabulary`/
`get_learning_summary` for 15 minutes, keyed by URL (and `min_srs_stage`
where it applies); `lookup_items`/`get_jlpt_levels` per string instead, in a
bounded LRU, since a generated text's distinct tokens never expire on their
own. `get_jlpt_levels` batches transparently over the server's own 2000-item
cap. `clear_cache()` drops all of it -- called from `PUT /api/settings`
whenever `kanji_trainer_mcp_url` changes, since a cache entry is keyed by the
old URL and would otherwise linger.

`GET /api/kanji-trainer/status` (`app/api/kanji_trainer.py`) is the Settings
screen's "Test connection" button: always HTTP 200 (it reports the
connection's state, it is not itself failing), bypassing the client's cache
with a `fresh` call so the button always tests the live connection, but still
refreshing the cache with whatever it got. `known_kanji`/`known_vocabulary`
are the lengths of the full known lists, not anything from the summary: its
per-state `counts` ignore the Guru threshold, and its JLPT breakdown only
covers subjects the JLPT snapshot lists. Fetching the lists also warms the
cache that text generation reads next.

## Known gaps

- No domain tables yet -- `app_settings` is the only table. Reading texts,
  progress and statistics arrive with their own issues.
- No frontend (#3), no Docker/deploy/CI (#4).
- No authentication. Single user, LAN only -- the same assumption the other
  stacks make.
