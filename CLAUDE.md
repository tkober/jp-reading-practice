# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## What this is for

A Japanese reading practice app: generates reading texts at the learner's
level, using what the other apps in the suite -- chiefly
[kanji-trainer](https://github.com/tkober/kanji-trainer) -- already know
about their vocabulary. See `REQUIREMENTS.md` for the full concept (epic #1)
and the open questions that are not decided yet.

This repository holds the backend skeleton (issue #2), the Angular frontend
skeleton (issue #3), deployment (#4), the Kanji Trainer MCP client (#5) and
the text analysis backend (#7 -- tokens, furigana, JLPT, metrics; see "Text
analysis" below). The frontend has no reading screen of its own yet (#6's
design and #9's rendering are separate issues); everything below describes
what actually exists, not a preview of what a later issue will add.

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

## Text analysis (issue #7)

A pure, synchronous module (`app/analysis.py`'s `analyze(text, known,
jlpt_lookup)`) that turns a Japanese text plus the learner's known set into
tokens and metrics -- nothing in it calls an LLM or MCP. #8 (measuring a
generated text) and #9 (rendering its tokens) are both built on this one
function; only `POST /api/analysis` (below) wraps it with the live calls.

**Tokenisation** (`app/furigana.py`) is fugashi + unidic-lite, the same
pairing as jp-conversation-practice's `backend/app/furigana.py`, whose
ruby-only-over-kanji splitting, okurigana alignment, whole-word fallback,
`_SURFACE_READINGS` table and graceful `None` on a broken dictionary are
ported here rather than re-derived -- the one real change is working per
token rather than per transcript line, since a `Token` needs its own lemma/
reading/part-of-speech, not just a flat ruby list.

**A token's base form is `orthBase`, never unidic's own `lemma` feature**
(`furigana._base_form`). `lemma` is a normalised dictionary headword that
often does not name the word as it is actually written: a kanji spelling
nobody uses any more for several everyday verbs (居る for いる, 出来る for
できる, 有る/無い/呉れる/為る the same way), a katakana pronunciation
instead of any written form for many proper nouns (金沢 -> lemma "カナザワ"),
and, worse, sometimes a genuinely *different word* that merely shares a
reading (撮る, "to photograph", surface 撮っ -> lemma "取る", "to take").
`orthBase` is the modern written base form in every one of those cases
(行く, できる, 金沢, 撮る), with `kanaBase` (not `pronBase`, which carries
phonetic artefacts like vowel lengthening) folded to hiragana as its own
reading -- `Token.lemma`/the reading used for every lookup below, never the
*surface's* own reading (`Token.reading`, e.g. いき for 行き), which stays
what it always was, for ruby display.

`analysis.lookup_candidates(raw)` is the one function every external-list
lookup (JLPT, the known-vocabulary match, and the dictionary once #9 wires
it up) goes through: `(lemma, lemma_reading)` first, then -- only on a
miss, never preferred -- `(alt_lemma, lemma_reading)`, unidic's own `lemma`
feature, kept only for the cases it is still useful for: a kana-written
word's kanji headword (こと has no kanji of its own to look a kanji-keyed
list entry up by; its `alt_lemma` is 事) and the handful of common verbs
above whose *modern* writing has no kanji at all but whose *older* one
might still be what a list is keyed by. `撮る`/`取る` is exactly why the
order is never reversed: `orthBase` is right there, and `alt_lemma` would
send the wrong word to every list that does have 撮る in it.

**The furigana rule** (`furigana.is_reading_composed`, called from
`analysis._build_token`): a word with kanji gets furigana iff it is not a
known vocabulary item (matched via `lookup_candidates` + `KnownSet.
knows_word`, see above) **and** (any of its kanji is unknown, or its reading cannot be
*composed* from its kanji's own known readings). "Composed" walks the same
kana/non-kana runs the ruby splitter uses: a kana run (okurigana) must
appear verbatim in the reading at the right position; a kanji run's
corresponding slice has to decompose into one known reading per character,
in order, tolerating rendaku (か→が etc.) and gemination (つ/ち/く/き→っ) at
the boundary between two kanji. A kanji missing from the known set simply
has no candidate reading, so "unknown kanji" and "does not compose" are not
actually two separate code paths -- see that function's docstring. 今日
(キョウ) fails the check even with 今/日 both known (the reading does not
follow from either); 学校 (がっこう) and 手紙 (てがみ) pass it only because
gemination/rendaku are tolerated at the boundary.

**The known set** (`app/known_set.py`) is a plain `KnownSet` (kanji
character -> known readings, vocabulary lemma -> known readings) built from
`kanji_trainer.get_known_kanji`/`get_known_vocabulary` -- `build_known_set`
is pure, `fetch_known_set` is the one-line async wrapper. On'yomi is folded
to hiragana and kun'yomi is taken bare of any `.`-separated okurigana, per
the furigana rule's own wording -- both are defensive no-ops against
kanji-trainer's actual WaniKani-sourced data, which already stores on'yomi
in hiragana and kun'yomi already bare of okurigana (e.g. 飲's kun'yomi is
"の", not "のむ" -- confirmed against a real import while building this).
`nanori` (name) readings are excluded from composition on purpose: an
obscure name reading passing the "composed" check for an everyday word would
be wrong far more often than it would be right.

**JLPT levels** come from `kanji_trainer.get_jlpt_levels(url, items)`, never
from a copy kept in this app -- `app/api/analysis.py` batches every text's
distinct `lookup_candidates` pairs (both the primary and the fallback one,
via `analysis.collect_lemmas`) into one call before calling the pure
`analyze()` a second time with the results (the first, throwaway call is
only there to get the token list to collect lemmas from -- tokenising twice
costs nothing, fugashi runs in well under a millisecond per sentence).
`_build_token` prefers the primary candidate's result and only reads the
fallback's `jlpt` (never its `kanji` breakdown, which would not line up
with `Token.kanji`'s own characters -- see `_build_token`'s comment) when
the primary one is `null`.

**Metrics** (`Metrics` in `models.py`): `characters` is kana + kanji + latin
letters/digits in the raw text, no punctuation or whitespace -- what
"characters per minute" would be measured against. `words` is tokens with
`is_word` (every part of speech except 助詞/助動詞/補助記号/whitespace;
numbers count) -- what "helps per 100 words" would be measured against.
`kanji_total`/`kanji_unknown` count kanji *occurrences*, not distinct
characters, and deliberately exclude 々/〆 (never a Kanji Trainer subject of
their own, so counting one would always show up as an unknowable "unknown
kanji"). `jlpt_mix` is the share of content words at each level, 5..1 plus
`unlisted`, summing to 1 unless there are no content words at all.

**Dictionary** (`app/dictionary.py`, `app/data/jmdict.sqlite`): JMdict
(EDRDG, CC BY-SA 4.0 -- see `app/data/LICENSES.md`), looked up by lemma +
reading for the word popover's part of speech and first three English
glosses. Built by `backend/scripts/build_jmdict.py` (downloads
`JMdict_e.gz`, ~10 MB, and writes a ~49 MB SQLite of lemma/reading/pos/
glosses only -- no example sentences, no cross-references) -- gitignored,
not committed, built once by a developer and again by `backend/Dockerfile`'s
`jmdict-builder` stage on every image build. `lookup()` returns `None`
rather than raising when the file has not been built, the same shape of
degradation `kanji_trainer.py`'s `KanjiTrainerUnavailable` is for the known
set. No HTTP endpoint for it yet -- #9's popover is expected to add one;
issue #7 only needed the module and its tests.

**`POST /api/analysis`** (`app/api/analysis.py`) is the debug endpoint for
development and for #8: `{text}` -> the full `TextAnalysis` plus
`kanji_trainer_error`. If the Kanji Trainer is unreachable, it analyzes with
an empty known set and no JLPT levels instead of failing the request --
every kanji looks unknown and every word's `jlpt` is `null`, same spirit as
`GET /api/kanji-trainer/status`'s "always 200" -- and the English reason
goes in `kanji_trainer_error` rather than a dedicated status shape, since
the whole response *is* the analysis either way.

**Image size.** fugashi + unidic-lite add roughly 250 MB (unpacked,
memory-mapped) to the backend image, same as jp-conversation-practice's own
documented footprint; `jmdict.sqlite` adds another ~49 MB. Together that is
a sizeable jump for this image, accepted because both are the practical
choice for what they do locally with no API cost per request -- see
`scripts/build_jmdict.py`'s own module docstring for why a ready-made
PyPI package (e.g. `jamdict`, ~100 MB including data this app does not use)
was not used instead.

## Frontend

Angular 22, zoneless, signals -- same stack as kanji-trainer and the other
apps in the suite, see that repo's CLAUDE.md for the general shape this one
copies (`core/api.ts`'s `rethrow()`, `core/unreachable.ts`'s
`isBackendUnreachable()` for the T6 error state). `frontend/src/app/pages/
{read,history,stats,topics}` are placeholder pages (`sumi-page` +
`sumi-empty-state`) until their own issues give them something real to show;
`pages/settings` is the one real screen so far, built against the backend's
existing `GET/PUT /api/settings` and `GET /api/settings/models`.

`frontend/src/app/features/read/{gate,setup,reading,questions}` are the
approved design's screens (issue #6), built against `frontend/src/app/
preview/` fixtures until #9+ wire them to real data -- `ng serve` and open
`/preview` (dev mode only, see `preview.routes.ts`'s doc comment) to click
through every state. #21 moved every screen off its own app-local
prototype (`proto/`, now deleted) onto the matching Sumi UI component:
`sumi-reading-text` for the running text and its per-word reading peeks,
`sumi-popover` for the word lookup (anchored on desktop, a bottom sheet on
phone -- `ReadingScreen` projects the word/meanings/actions content into
it, the overlay shell itself is the library's), `sumi-side-panel` for the
"ask about this text" chat, the extended `sumi-session-bar` for the
reading header (elapsed/pause/chat, no "End session"), `sumi-choice-
question` for the comprehension questions, `sumi-tile-picker` for the
topic grid and `sumi-share-slider` for the JLPT mix. One library gap found
along the way: `sumi-reading-text`'s `wordActivated` event carries only
the activated word's `DOMRect`, not the element itself, which `sumi-
popover`'s `[anchor]` input wants live (so it can re-measure on resize/
scroll) -- `ReadingScreen.resolveAnchorElement` bridges the two via
`document.elementFromPoint`, see its own doc comment.

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
