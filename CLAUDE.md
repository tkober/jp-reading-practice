# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## What this is for

A Japanese reading practice app: generates reading texts at the learner's
level, using what the other apps in the suite -- chiefly
[kanji-trainer](https://github.com/tkober/kanji-trainer) -- already know
about their vocabulary. See `REQUIREMENTS.md` for the full concept (epic #1)
and the open questions that are not decided yet.

This repository currently holds the backend skeleton (issue #2) and the
Angular frontend skeleton (issue #3): no domain logic, no deployment.
Everything below describes what actually exists; do not take it as a preview
of what #4 and later issues will add.

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

```bash
cd frontend
npm ci                      # install, incl. the sumi-ui submodule's peer deps
npm start                    # ng serve on :4200, proxies /api to :8000
npx ng build                 # production build -- the correctness gate (type-checks templates)
```

```bash
./dev.sh                     # backend + frontend together; needs backend/.env
BACKEND_PORT=8010 FRONTEND_PORT=4210 ./dev.sh   # overridable for parallel sessions
```

The frontend has no spec files, so `ng test` finds nothing yet -- `ng build`
is the correctness gate, same as the other apps in the suite.

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

## Frontend

Angular 22, zoneless, signals -- same stack as kanji-trainer and the other
apps in the suite, see that repo's CLAUDE.md for the general shape this one
copies (`core/api.ts`'s `rethrow()`, `core/unreachable.ts`'s
`isBackendUnreachable()` for the T6 error state). `frontend/src/app/pages/
{read,history,stats,topics}` are placeholder pages (`sumi-page` +
`sumi-empty-state`) until their own issues give them something real to show;
`pages/settings` is the one real screen so far, built against the backend's
existing `GET/PUT /api/settings` and `GET /api/settings/models`.

`core/api.ts`'s `kanjiTrainerStatus()` calls `GET /api/kanji-trainer/status`
(see "Kanji Trainer (MCP)" above) for the Settings screen's "Test
connection" button. A 404 there is not "the backend is unreachable" (see
`core/unreachable.ts`'s doc comment) -- it means a backend older than issue
#5, and `KanjiTrainerStatusUnavailable` is the dedicated error type the
Settings screen checks for, to say so instead of showing a generic failure.

## Sumi UI

`frontend/sumi-ui` is a git submodule (`tkober/sumi-ui`, shared with the
other apps in the suite) -- clone this repo with `git clone
--recurse-submodules`, or run `git submodule update --init` in an existing
checkout; **never `npm install` inside it**, it compiles against this app's
own `node_modules`. Wired in per sumi-ui's README ("Using Sumi UI in an
app"): `tsconfig.json`'s `paths` resolves `sumi-ui/*` straight to the
submodule's TypeScript sources (no separate library build),
`angular.json`'s `stylePreprocessorOptions.includePaths` is the Sass load
path `styles.scss` needs for `@use 'sumi-ui/projects/sumi-ui/styles/sumi'`,
and the library's `@font-face` rules ship as their own non-injected
`sumi-fonts.css` bundle, linked separately in `index.html`.

`provideSumi({ accent: 'tokiwa', motif: 'moon', pattern: 'sayagata',
companion: 'fukurou' })` in `app.config.ts` -- all four are **placeholders**
until the real design lands in tkober/sumi-ui#25, with one asterisk:
`accent: 'tokiwa'` (tokiwa-iro, `#007b43`) is a preset sumi-ui added
specifically for this app (tkober/sumi-ui#82), so it is a considered choice
already, just not yet confirmed as final the way #25 will settle it. Update
the inline SVG favicon in `index.html` by hand if the accent ever changes --
it is not derived from `provideSumi()`.

Nav: Read · History · Stats · Topics · Settings (`app.ts`'s `nav`), routes
`/read` (default), `/history`, `/stats`, `/topics`, `/settings`
(`app.routes.ts`). `sumi-app-shell` collapses this into a bottom tab bar on
its own below 720px -- nothing in this app's own code handles that.

## Deployment

Two GHCR images, built by GitHub Actions on push to `main`:
`ghcr.io/tkober/jp-reading-practice-backend` and `-frontend`. The workflows
also build (without pushing) on `pull_request` -- there is no Docker in the
dev environment this repository is usually worked on from, so this is what
catches a broken Dockerfile before it reaches `main`. Only the frontend
publishes a port, so no CORS is involved and the backend port stays
unpublished; the backend's `/api/health` is its container healthcheck, and
the frontend's `depends_on` waits for it to report healthy before starting.

Ports already taken on the target host: 2222, 3141, 5432, 5678, 5900, 8000,
8001, 8080-8087, 8765, 18789. Hence **8088**.

Database bootstrap is manual, like the other projects: `dbeaver/` holds the
SQL to create the roles and database, run by hand against `postgres-core`
with the `${...}` password placeholders substituted; its two statements reuse
exactly what `dev/initdb/01-roles.sql` does locally. `dbeaver/verify.sql`
exists because the failure mode is silent -- Postgres answers a missing role
with the same `28P01` it uses for a wrong password, so "authentication
failed" does not tell you which of the two happened.

The stack directory (`deploy/jp_reading_practice/`) is meant to be copied
into the `compose-stacks-unraid` repository. `compose.yaml` at the repo root
is the local mirror of it, down to creating both Postgres roles via
`dev/initdb`.

**`index.html` must never be cached, the hashed assets always.** nginx serves
the shell with `Cache-Control: no-cache` and everything with a content hash
in its name as `immutable` for a year. Without the first, a browser reuses
the old shell after a redeploy and stays pinned to the previous bundle --
with no symptom except that the new code is simply not there, which costs an
hour to diagnose because the server is serving the right files the whole
time. `sumi-fonts.css` keeps the same name across builds (it is not part of
the hashed bundle), so it gets its own `no-cache` rule rather than falling
into either bucket; the manifest and its icons are revalidated short-lived
instead, since their names are stable too but redesigning one should not pin
the old version in every browser that has seen it for a year.

**`/api/` gets a 180s `proxy_read_timeout`, not kanji-trainer's 120s.** Text
generation calls an LLM synchronously, inside the request -- there is no
background task to poll the way kanji-trainer's WaniKani import works, so
the one request genuinely can take a while and nginx must not cut it off
mid-completion.

**Installing it as a PWA needs TLS.** Service workers are `[SecureContext]`,
so over plain HTTP to a LAN address (`http://<host>:8088/`) one cannot
register. The app works normally in a browser there; "installed on the
phone, offline" needs a reverse proxy with a certificate in front. Nothing in
the code assumes either way.

**This backend depends on Kanji Trainer's `MCP_ALLOWED_HOSTS`.** It calls
Kanji Trainer's read-only MCP server at `KANJI_TRAINER_MCP_URL`
(`http://192.168.2.230:8086/mcp` in the deployment); that server's own
DNS-rebinding check rejects any request whose Host header is not in its
`MCP_ALLOWED_HOSTS` allowlist, so the Kanji Trainer deployment's env must
list `192.168.2.230:8086` there (see `deploy/jp_reading_practice/env/
jp-reading-practice-backend/.env.example`) or every call here gets back an
HTTP 421.

## Known gaps

- No domain tables yet -- `app_settings` is the only table. Reading texts,
  progress and statistics arrive with their own issues, and Read, History,
  Stats and Topics are placeholder pages until then.
- No authentication. Single user, LAN only -- the same assumption the other
  stacks make.
