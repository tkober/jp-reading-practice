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
on an engine it builds itself from the owner URL (only then does it load
`alembic.ini`'s logging config -- in-process it would mute the app's own
loggers);
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

**Compound particles (複合助詞)** (`app/analysis.py`'s `_mark_compound_particles`,
run once per paragraph right after `tokenize_paragraph`, before `_build_token`):
unidic splits these into their parts, so the verb inside would otherwise count
as a content word -- について tokenises as に/つい(lemma つく)/て, and that つく
would get its own JLPT level, count toward `words`/`jlpt_mix`, and be tappable.
The fixed sequences folded into grammar (`is_word = False`, same as an ordinary
particle -- no JLPT, no word count, no peek) are: について/につき (つく),
に対して/に対し/に対する (対する), によって/により (よる), として/とし/とする
(する), にとって (とる), に関して/関し/関する (関する), において (おく),
をめぐって/めぐり/めぐる (めぐる), に基づいて/基づき/基づく (基づく), に向け
て/向け/向ける (向ける), とともに/と共に, に従って/従い/従う (従う) -- both
the renyoukei-alone connective (bare in formal/news register: に対し、,
をめぐり議論 -- common in real NHK text) and the rentaikei form modifying a
following noun directly (に対する対応, をめぐる議論) are included, since both
are the same particle structurally, not just the て-form. における is not
handled (おける conjugates through an extra classical auxiliary, り, rather
than simply dropping て) and neither is んにつきまして's super-polite につき
ます(して) -- both fall through unmarked, a known, documented gap.

Matched by the verb's own `lemma` (`orthBase`, never unidic's own `lemma`
feature -- see `_base_form`), which is what tells a grammaticalised use apart
from a same-reading content verb: 着く/就く/置く/巡る (kanji) never collide
with つく/おく/めぐる (kana) the way 撮る/取る already don't (see above). Two
pairs share a lemma with no kanji/kana split at all and need an extra guard:
つく also covers the literal "stick to" sense (手についた, never without a
following て) and the lexicalised ついてくる/いく (犬が私についてきた, not
folded into について -- a plain verb continuing the clause instead, 犬が私
について歩いた, is *not* caught, another documented gap); とる also covers
literal "take" chained onto a benefactive/aspectual auxiliary (友人にとって
もらった, 母にとっておいた). として has its own guard against と's other job,
the quotative/volitional "〜(よ)うとした" ("tried to"), which always has a verb
(not a noun) right before と. A bare renyoukei/rentaikei match is also rejected
when the next token is a 助動詞 completing that verb's *own* finite predicate
(対した, とした, 向けた are complete sentences, not に対して/として/に向けて
with the connector dropped).

Stored texts keep whatever analysis was computed for them at generation time
-- this only changes what a *newly* generated or re-analysed text looks like.
Measured against real text (NHK News Web RSS, all 8 category feeds, 1,202
titles+descriptions, ~41,500 tokens): 404 tokens (1.6% of what `words` counted
before) move from content word to grammar, affecting 295 of the 1,202 texts
(24.5%). Every pattern above fired at least once; the most common were とし/
として (90), つく's family (84), よる (69), and めぐる's family (54).

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
approved design's screens (issue #6), still built against `frontend/src/app/
preview/` fixtures -- issue #9 wires `pages/read/` to them with real data
instead, see below. `ng serve` and open
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
topic grid and `sumi-share-slider` for the JLPT mix. The word popover
anchors on `wordActivated`'s `element` (sumi-ui#108), and the session bar's
chat action takes its look from `[sumiSessionBarAction]`. Issue #9 added two
more optional inputs so these components stayed presentational while the
word popover's action buttons (#10) and the session bar's chat action
(#11) did not exist yet: `ReadingScreen.chatEnabled` (default `true`, so
every existing `/preview/reading*` route is unaffected) and
`WordDetails.actions` (optional -- an absent/empty list simply renders no
action buttons). `/read/:sessionId` passes `chatEnabled: true` since #11
(see "Tutor chat" below) -- it never goes back to `false`.
`GateScreen.kanjiTrainerErrorNote` (also new, also optional, default
`null`) follows the same pattern for the one banner the gate needed that
the approved design did not have a slot for yet.

`core/api.ts`'s `kanjiTrainerStatus()` calls `GET /api/kanji-trainer/status`
(see "Kanji Trainer (MCP)" above) for the Settings screen's "Test
connection" button. A 404 there is not "the backend is unreachable" (see
`core/unreachable.ts`'s doc comment) -- it means a backend older than issue
#5, and `KanjiTrainerStatusUnavailable` is the dedicated error type the
Settings screen checks for, to say so instead of showing a generic failure.

### Reading sessions (issue #9)

`/read` (`pages/read/read.ts`) owns everything *before* a session exists:
setup (topics from `GET /api/topics` plus a synthetic "Surprise me" tile,
`slug: "surprise"`), the generating state while `POST /api/texts` runs (it
can take over a minute; nginx's `/api/` proxy allows 180s, see
"Deployment"), the gate once it returns, and the full-screen error for a
502/other failure (Retry re-sends the same payload, Back returns to
setup). A 409 (no OpenAI key) does not go to the error screen -- it flips
`hasOpenAiKey` back to `false` and returns to setup, reusing that banner
rather than inventing a second way to say the same thing. The gate's
"Start" is the one thing that actually creates anything stateful here:
`POST /api/sessions {text_id}`, then `router.navigate(['/read', id])`.

`/read/:sessionId` (`pages/read/read-session.ts`) owns the running session
and picks reading/questions/summary from `GET /api/sessions/{id}`'s own
`status` on every load (`status-routing.ts`'s `screenForStatus`, unit
tested) -- a reload or switching apps on the phone resumes exactly where
the reader was, active time included, since the heartbeat (below) has
already pushed it to the server. "Read again" (from the summary) creates
a *new* session on the same `text_id` and navigates straight into reading,
skipping the gate; "New text" goes back to `/read`.

**Overrides are opt-in, never shadowed from the preset.** `setup.types.ts`'s
`DIFFICULTY_PRESETS` table (issue #6) now matches the backend's own
`presets.py` numbers exactly (percent/100 instead of a fraction) so the
setup screen's promise and the gate's measured values agree -- but
`ReadPage` only ever sends `overrides.style`/`unknown_kanji_target`/
`jlpt_mix` for a field the learner actually changed inside "Adjust"
(tracked per field, reset whenever the preset itself is changed). Left
untouched, `POST /api/texts` gets only `{topic_slug, length, preset}`, so
the backend's own preset -- and the *topic's* own `default_style` -- apply
exactly as `api/texts.py` already resolves them (issue #8), rather than
this screen's own UI-friendly numbers silently overriding the topic's
style default on every single generation.

**The reading screen's tokens are mapped, not rendered directly.**
`pages/read/token-mapping.ts`'s `mapApiParagraphsToReadingText` (pure,
unit tested) turns the backend's full per-word `Token` analysis into
`sumi-reading-text`'s lean `SumiReadingWord` (`{id, text, reading?,
unknown?, plain?}`): `is_word === false` (particles, auxiliaries,
punctuation) -> `plain`, ordinary running text that is not focusable,
tappable or peekable (sumi-ui#112); no kanji at all -> no reading (nothing
to peek over a kana word's own spelling); `needs_furigana` -> `reading`
set, `unknown: true` (always-visible ruby); a kanji word that does not
need it (known, or every kanji composes) -> `reading` set, `unknown` left
falsy (peekable on hover/focus/long-press). The mapping also returns
`tokensById`, which `ReadSessionPage` uses to resolve a tapped or peeked
word back to its token.

**Active time** (`pages/read/active-time-tracker.ts`'s `ActiveTimeTracker`,
unit tested) counts only while not manually paused, the document is
visible, and the reader is not idle (no pointer/key/scroll/touch/wheel for
`IDLE_TIMEOUT_MS`, 60s) -- a manual pause counts into `pausedMs` instead,
while a hidden document or an idle stretch is counted into *neither*, on
purpose: it is lost real time, not "paused" in the session's own sense.
The class has no timer of its own -- every method takes (or defaults to
the injected clock's) an explicit timestamp and settles elapsed time
against it on every call, which is what makes a single `tick()` call that
spans the idle threshold split correctly (idle can start *mid-interval*,
since nothing calls in to mark the exact moment) and what lets the spec
drive it with plain incrementing numbers, no fake timers. `ReadSessionPage`
calls `tick()` every second (for the live elapsed label) and wires
`visibilitychange` plus pointer/key/scroll/touch/wheel listeners to
`setVisible`/`noteActivity`; a manual pause (`sumi-session-bar`'s own pause
button) blurs the text (existing design, unchanged) and calls
`setPaused(true)`. The heartbeat (`PUT /api/sessions/{id}/time`, monotonic
server-side -- never lowers a stored value) fires every 15s, on pause, and
on `Done`; `visibilitychange` going hidden instead calls
`Api.heartbeatKeepalive` -- a plain `fetch(..., {keepalive: true})`
bypassing `HttpClient`, since `HttpClient` has no `keepalive` option and an
ordinary request can be cancelled by the very backgrounding it is trying
to report.

**Word interactions.** A hover/focus/long-press peek (`sumi-reading-text`'s
own `readingPeeked`, only ever fired for a peekable -- known, has a
reading -- word) calls `POST /api/sessions/{id}/helps {kind:
"reading_peek", token_id}`; `ReadSessionPage` also tracks peeked lemmas
client-side (`peekedLemmas`) so a repeat peek of the same word never even
reaches the network, on top of the backend's own per-session dedupe. A tap
(`wordActivated`) on a token with `is_word` calls `POST .../lookups`,
which both logs a `word_lookup` help and returns the dictionary/JLPT/Kanji
Trainer details the popover shows; the popover opens immediately with a
"Loading…" placeholder (`WordDetails`, no `actions`) and is replaced once
the response lands, or on error if it does not -- only once it lands does
`WordDetails.actions` get the three LLM helps below, never while the
lookup itself is still pending. `GET /api/sessions/{id}/summary`'s
`looked_up_words` is fed straight into `SummaryScreen`.

### LLM helps: Explain word / Translate sentence / Explain grammar (issue #10)

The word popover's first three action buttons (`WORD_ACTIONS`, `pages/read/
read-session.ts`) -- labels and weights exactly as the approved design/
preview fixture (`preview/fixtures/word-lookup.fixture.ts`'s own
`WORD_ACTIONS`) show them: **Explain word** (+2), **Translate sentence**
(+3), **Explain grammar** (+3). Its fourth, **Ask tutor** (+3), is issue
#11's own scope -- see "Tutor chat" below, it does not call `Api.assist()`
at all. "Translate sentence"/"Explain grammar" act on the sentence
*containing* the tapped word, not the word itself -- for a learner-dragged
*part* of it instead, see "Partial-sentence selection" below (issue #32).

**`app/sentences.py`** is the one place that decides where a sentence
ends: `split_sentences(paragraph_index, tokens)` takes `(token_id,
surface)` pairs (either `Token` or the plain dict a `GeneratedText.
analysis` row stores both work, since only those two fields are read) and
groups them into `Sentence`s -- a sentence ends right after `。！？!?` and
any closing bracket/quote (`」』）`) directly following it, so
「そうだ。」is one sentence, not two. `find_sentence()` locates the one
containing a given token id. A sentence key has the same `"<paragraph>-<n>"`
shape as `Token.id` (`"<paragraph_index>-<sentence_index>"`, never compared
to a token id directly, only each used as its own cache/dedupe key).

**`POST /api/sessions/{id}/assist` `{kind: "explain"|"translate"|"grammar",
token_id}`** -> `{kind, answer, cached, counted, weight}` (`api/
sessions.py`). Only in status `reading` (409 otherwise, same as every other
reading-phase endpoint); `explain` only for an `is_word` token (422 on a
particle) -- `translate`/`grammar` accept any token, since they act on its
sentence. The *target* `HelpEvent`/`help_answers` dedupe on is
`"<sentence key>:<lemma>"` for `explain` (it explains the word *in this
sentence*, so the same lemma in another sentence is a different question)
and the sentence key for `translate`/`grammar` -- see `db.HelpEvent`'s
docstring.

**The cache (`help_answers`)**: one row per `(text_id, kind, target)` --
the same question about the same text is answered once *ever*, reused by
any later session, even a different learner re-reading the same generated
text. A cache hit skips the OpenAI call entirely (`cached: true` in the
response) and this session's own help event still gets logged (so
`helps_per_100_words` counts it) but at `cost_usd: 0.0` -- only the
session whose own request actually generated the answer carries its real
cost. The help event itself is still deduped per `(session_id, kind,
target)`, exactly like `reading_peek`/`word_lookup`: a repeated ask of the
same target in the same session is `counted: false` regardless of
`cached`.

**Prompts (`app/help_prompts.py`)**: one shared tutor-role frame (patient,
English-speaking-learner-calibrated, plain English prose, no markdown, no
romaji, Japanese quoted as written), plus three builders that each give
the model the *whole* text as context, then the specific target:
`build_explain_word_instructions` (meaning in this sentence, dictionary
form + what the inflection does, a nuance/collocation note if relevant,
<=80 words), `build_translate_sentence_instructions` (a natural English
translation, then one short line on anything a learner would likely
misread, <=60 words), `build_explain_grammar_instructions` (the 1-3
grammar points that actually carry the sentence's meaning, <=120 words).
The word limits are asked for, not enforced in code -- same spirit as the
length target in `prompts.py`'s own generation frame.

**The call itself (`app/assist.py`)** is a plain chat completion against
`RuntimeConfig.help_model` -- no Structured Outputs (unlike
`generation.py`'s forced JSON schema): there is no shape to enforce beyond
"short English text", which the prompt's own word limits already ask for.
Same `httpx`/`GenerationError` status convention as generation (409 no
key, 502 for anything upstream, a refusal, or an empty response), but a
60s timeout rather than generation's 120s margin -- one short call does not
need as much room. Cost comes from `pricing.cost_usd()` against
`config.help_model`, `null` for a model `pricing.MODEL_RATES` does not
know (same convention as `GeneratedText.cost_usd`).

**`GET /api/sessions/{id}/summary`'s `assists_cost_usd`** sums
`HelpEvent.cost_usd` over the session -- `NULL` for `reading_peek`/
`word_lookup` (not an LLM call) and `0.0` for a cached assist both count as
0, so only an assist this session's own request actually generated adds
anything. Not shown on screen yet (History/Stats are still placeholders,
issue #12+); the frontend's `SessionSummaryApi` carries the field purely
so the type matches the backend.

**Frontend wiring (`pages/read/read-session.ts`)**: once a word's lookup
resolves, `WordDetails.actions` gets `WORD_ACTIONS`; a click on one calls
`Api.assist()`, disables all three buttons (`ReadingScreen.
wordActionLoading`, only the clicked one shows "Thinking…") until it
resolves, and renders the answer in `WordAnswer` (the popover's existing
answer block). A 409 (no key) or 502 (upstream) shows as that block's own
error text (`WordAnswer.isError`, red via `--sumi-wrong`) rather than a
page-level error -- `ApiError`'s own message (already a full sentence,
`core/api.ts`'s `rethrow()`) is shown verbatim. Opening a different word,
or closing the popover, clears both the answer and any in-flight loading
state.

### Partial-sentence selection (issue #32)

**Desktop only, by the owner's decision** (2026-10-18): a mouse drag
across the running text, not the phone's two-tap range mode the issue's
own proposal also considered -- a long press already peeks the reading on
the phone (issue #9), and the owner decided to ship the desktop gesture
alone for now rather than resolve that collision.

**`sumi-reading-text` (`sumi-ui/practice`)** gained the gesture itself,
opt-in via a new `rangeSelection` input (default `false`): a *mouse* drag
(`PointerEvent.pointerType === 'mouse'`) across at least two non-plain
words in one paragraph resolves to a `rangeSelected` event (`{ startId,
endId, words, element }`) -- the native selection's start/end are each
snapped inward to the nearest real word (a plain token at either edge
cannot itself be `startId`/`endId`, only ride along inside `words`), then
the native selection is cleared and the trailing `click` a drag's
`mouseup` still triggers is suppressed, so it never also fires
`wordActivated`. Anything short of that (inside one word, a drag crossing
a paragraph) is left as an ordinary, copyable selection. A new
`selectedRange` input (`{ startId, endId } | null`) then highlights every
word in that span, seamlessly (same background as `--selected`, no
per-word border, so adjacent words' backgrounds touch) including any
plain token caught in between. Touch/pen never start it at all.

**`ReadingScreen`** passes `rangeSelection=true` always and forwards
`selectedRange` straight through; on `rangeSelected` it re-anchors the
popover to the event's own `element` and emits the event up to
`ReadSessionPage`. `pages/read/sentence-for-token.ts` gained
`sameSentenceSpan(paragraphs, startId, endId)`, the same client-side
mirror of the backend's own sentence splitter the existing `sentenceForToken`
already is, so the page can tell a same-sentence span from a
cross-sentence one *before* even trying `/assist`.

**`ReadSessionPage.onRangeSelected`** opens the same `WordDetails` popover
a word tap would (`selectedWord`, `kind: 'range'`): the span itself as the
header (Japanese, no reading line, no dictionary/Kanji Trainer section at
all -- a span has none of its own), and either `RANGE_ACTIONS` (same
sentence) or just a note, "Select within one sentence.", and no actions
(crosses one). The two popover kinds (word vs. range) are mutually
exclusive -- opening either clears the other's own selection/highlight,
and closing the popover clears `selectedRange` too (brief).

**`RANGE_ACTIONS`** (`read-session.ts`): **Translate part** (+2),
**Explain grammar** (+2), **Ask tutor** (+3) -- a span counts *less* than
the whole sentence (the owner's decision, see below), while "Ask tutor"
stays +3 either way (it is a question, span or not). The first two call
`Api.assist()` with `end_token_id` set to the span's end (`token_id` stays
its start); "Ask tutor" opens the chat panel with `focus_token_id` *and*
`focus_end_token_id` set, rather than just the single-word focus issue
#11 added.

**`POST /api/sessions/{id}/assist`** gained two kinds, `translate_part`/
`grammar_part`, taking the same body plus `end_token_id` (`AssistRequest`,
`models.py`): `token_id` is the span's start. **Validated** (`app/
sentences.py`'s `resolve_span`, shared with the chat's own span focus
below): both tokens in the *same* sentence, start not after end, at least
two *word* tokens in the inclusive span (a plain token caught between two
real ones still counts towards the span's own *text*, never towards this
minimum) -- else 422 with a clear message; an unresolvable `end_token_id`
is a 404, same as the existing `token_id` check. **Target**
(`sentences.span_target`): `"<sentence key>:<start token id>-<end token
id>"`, e.g. `"0-1:0-3-0-7"` -- parsed back apart by `sentences.
parse_span_target` (the three pieces have no hyphen of their own, so the
split is unambiguous) wherever it is reused unparsed, see below. Cached in
`help_answers` and deduped in `help_events` exactly like the three
whole-sentence kinds -- the span target is just a longer string in the
same `target` column, no schema change. **Weights** (`helps.py`):
`TRANSLATE_PART_WEIGHT`/`GRAMMAR_PART_WEIGHT`, both 2. **Prompts**
(`help_prompts.py`): `build_translate_part_instructions`/
`build_explain_grammar_part_instructions` -- the same shape and word
limits (60/120) as their whole-sentence counterparts, with the span
itself as the thing to translate/explain and its sentence folded in as
extra context on top of the whole text every builder already gives the
model.

**Tutor chat** (`ChatRequest`): a new `focus_end_token_id`, alongside the
existing `focus_token_id`, turns the focus into that span rather than the
whole sentence containing it -- validated by the same `resolve_span` (422/
404 the same way), ignored entirely without `focus_token_id`. The prompt
prefix becomes `"About this part of a sentence: <span> (in: <sentence>)"`
(`help_prompts.focus_question_part`) instead of `"About this sentence:
<sentence>"`. `ChatMessage.focus_sentence_key` stores the span *target*
(`sentences.span_target`) rather than a plain sentence key for this case
-- again no schema change, since nothing ever reads that column as
anything but an opaque string outside `_answered_history`'s own replay,
which tells the two shapes apart with `parse_span_target` and re-resolves
the span's text from its two token ids (never stored redundantly, same
spirit as a plain focus sentence's text never being stored either).
Counted exactly like any other tutor question (`kind: "tutor"`, weight 3,
`target: "chat:<user message id>"`, always unique) -- a span changes
nothing about the counting, only the prompt.

**Previews**: `/preview/reading-range` and `/preview/reading-range-answer`
simulate a real mouse drag (`Selection`/`Range` + a dispatched
`pointerup`) across two real words in `READING_TEXT`, so the resolution
path exercised is the exact same one a learner's own drag would take --
same convention the existing word/answer/peek preview variants already
use.

### Backend: `reading_sessions` / `help_events` (issue #9)

`reading_sessions` (`db.py`): one row per attempt at a text -- reading a
text again (`POST /api/sessions` with the same `text_id`) always starts a
*new* row, never reuses one. `status` walks `reading -> questions ->
finished`, driven entirely by `api/sessions.py`; `active_ms`/`paused_ms`
are the heartbeat's own monotonic running totals; `answers` is one entry
per question (chosen option index, or `null`), index-aligned with the
text's own `questions`; `comprehension_correct` is `null` until
`finished`, then the number of questions answered correctly.

`help_events`: one row per *first* occurrence of a help kind for a given
*target* in a given session -- the unique constraint on `(session_id,
kind, target)` is the entire dedupe (`ON CONFLICT DO NOTHING`; a repeat
returns `counted: false`, never an error). `kind` is a plain string
column, not a DB enum, which is exactly what let `tutor` (issue #11, see
"Tutor chat" below) arrive with no schema change here at all -- its
`target` is simply unique per question, so the same dedupe that makes a
repeated `explain` a no-op never actually fires for it; every question
counts. `helps.py` is the one place every weight lives. `target` (issue
#10; backfilled from the pre-existing
`lemma` column, which is exactly what every row before #10 deduped on) is
the lemma for `reading_peek`/`word_lookup`, sentence key + lemma for
`explain`, and the sentence key (`sentences.Sentence.key`) for
`translate`/`grammar` -- see "LLM helps" above. `token_id`/`lemma`/
`surface` ride along unconditionally (not just for word kinds) so the
summary can always join back to the exact occurrence that triggered the
help; `cost_usd` (issue #10) is `NULL` for a non-LLM help, `0.0` for a
cached assist, the real cost only for one this session's own request
generated -- see `assists_cost_usd` above.

`help_answers` (issue #10): the assist cache, one row per `(text_id, kind,
target)` -- `answer`/`model`/`usage`/`cost_usd` describe the one
generation call that produced it. Unlike `help_events`, this table has no
notion of session at all: it is shared across every session that ever
reads that text.

**`Token.lemma_reading`** (`models.py`, issue #7's `Token` gaining one more
field) is the lemma's own reading (`RawToken.lemma_reading`, unidic's
`kanaBase`), as opposed to `Token.reading`, the *surface's* own reading for
ruby display. The two differ for any conjugated word (食べました's surface
reading is たべました; its lemma's is たべる) -- the word lookup and the
summary's looked-up-words list both need the lemma's reading (what the
dictionary is keyed by), never the surface's. Defaults to `""` so a
`texts` row stored before this field existed still deserialises (issue #8
rows predate it; nothing re-analyzes them); `api/sessions.py`'s
`_lemma_reading` falls back to the surface reading for those rows.

`POST /api/sessions/{id}/lookups`'s known-status string ("Kanji Trainer:
Guru II" / "Not in Kanji Trainer" / "Kanji Trainer unavailable") reads
`kanji_trainer.lookup_items` and formats the result with a small, local
copy of kanji-trainer's own WaniKani-style stage names (its `app/srs.py`'s
`STAGE_NAMES`) -- there is no shared package between the two repos, same
situation `kanji_trainer.py`'s own module doc comment describes for the
rest of this client.

`GET /api/reading/pace` (mounted at a different prefix than the rest of
`api/sessions.py`'s router -- see `pace_router` in that module and its
second `include_router` call in `api/__init__.py`) is the median chars/min
over the last 5 finished sessions -- only each text's *first* finished read,
since a re-read is faster for reasons unrelated to the reader's pace --
falling back to a default of 150 until at least 3 exist; the setup screen's
duration estimate and the gate's own estimate both read it.

### Tutor chat (issue #11)

A side panel (`sumi-side-panel`, docked on desktop, a full-height sheet on
the phone) next to the text, opened from the session bar's "Ask about this
text" action (`ReadingScreen.chatEnabled` is `true` from `/read/:sessionId`
now) or from the word popover's fourth action, **Ask tutor** (+3, see "LLM
helps" above). Context is the whole text, plus -- optionally -- the
sentence containing whichever word "Ask tutor" was opened from. Only
available while the session is `reading` (409 otherwise, same as every
other reading-phase endpoint); the panel is never rendered for
`questions`/`finished` at all (`read-session.html`'s `@switch`).

**`chat_messages`** (`db.py`'s `ChatMessage`, one Alembic revision, `0005`):
one row per turn, `role` `"user"`/`"assistant"`, a plain string column (not
a DB enum) same spirit as `HelpEvent.kind`. `focus_sentence_key` is set
only on a user message that carried a focus; `model`/`usage`/`cost_usd`
only on an assistant message. No unique constraint at all -- unlike
`help_events`, this table is the actual conversation, not a dedupe ledger;
the chat's own counting lives entirely in `help_events` (below).

**`GET /api/sessions/{id}/chat`** returns the session's whole conversation,
oldest first -- what a reload replays into the panel. Available regardless
of the session's own status (the panel itself is never shown outside
`reading`, but there is no reason to 404 a read of history that still
exists once the session moves on).

**`POST /api/sessions/{id}/chat` `{content, focus_token_id?}`** ->
`{user_message, assistant_message, counted, weight}` (`api/sessions.py`'s
`post_chat`). `content` is validated non-empty and at most 1000 characters
(`ChatRequest`'s own `field_validator`, stripped before storing) -- a
violation is a plain Pydantic 422, no extra code needed. The user message
is stored *first* and kept even if the OpenAI call then fails (409 no key,
502 upstream, same convention as `/assist`) -- a resend is simply a new
question, there is nothing to retry server-side. `focus_token_id` resolves
to its sentence via `sentences.find_sentence` (issue #10's own module),
whose key is stored on the user message and whose text is folded into the
prompt for this one question only.

**The prompt (`help_prompts.build_tutor_messages`)**: the shared tutor role
(`_ROLE`, issue #10) plus the whole text plus chat-specific rules
(`_TUTOR_RULES`) as the system message -- answers in plain English, at most
120 words unless asked for more, never translate the whole text in one go
(offer to go sentence by sentence and start with the first), redirect
anything unrelated to the text/its words/its grammar back to it in one
short sentence. The session's earlier *answered* questions follow as
`user`/`assistant` turns, oldest first (`api/sessions.py`'s
`_answered_history`): a question whose call failed stays in the panel but is
never sent again, so a resend does not reach the model twice. Every focused
question -- past or new -- is sent as
`"About this sentence: <sentence>\n\n<question>"` (`focus_question`); the
stored message keeps the raw text and the sentence key. `app/assist.py`'s `generate_chat_answer` sends this `messages` array
as-is, sharing `generate_help_answer`'s own `_post_chat_completion`/
`_parse_completion` (so a no-key/upstream failure is handled identically)
and its 60s timeout -- both go through `RuntimeConfig.help_model`.

**Counting**: each question is one `help_events` row, `kind: "tutor"`,
weight 3 (`helps.py`'s `TUTOR_WEIGHT`), `target: "chat:<user message
id>"`. Unlike a word/sentence target, this is always unique, so the
dedupe `_log_help` shares with every other help kind never actually fires
for `tutor` -- every question is counted, on purpose (a conversation is
not a cacheable question, unlike the three LLM helps' own `help_answers`
cache, which the chat never touches at all). `GET /api/sessions/{id}/
summary`'s `helps_per_100_words` already summed every kind's weight, so
tutor questions fold in with no code change; `assists_cost_usd` likewise
already summed every `HelpEvent.cost_usd`, chat answers included.
`chat_questions` (new) is the count of `tutor` help events, for a session
screen to show later without recomputing it from the raw messages.

**Frontend (`pages/read/read-session.ts`)**: `chatMessages`/`chatOpen`/
`chatSending` signals, loaded from `Api.chatHistory()` alongside every
session load. "Ask tutor" (`onWordAction`'s `'tutor'` branch) closes the
word popover and opens the panel with the tapped word's sentence as the
next question's focus, shown as a small removable chip above the composer
(`ReadingScreen.chatFocus`/`chatFocusClear`, additive inputs/outputs, same
pattern `chatEnabled` set) -- resolved client-side by `sentence-for-
token.ts`'s `sentenceForToken`, a pure, unit-tested mirror of the backend's
own `app/sentences.py` splitter, used only to show the chip immediately
without a round trip (the backend resolves its own `focus_sentence_key`
independently from the same `focus_token_id`, so a mismatch here could
only ever affect this chip's display text, never counting). The focus is
consumed -- and the chip cleared -- the moment the next question is sent,
whether or not the answer itself succeeds; the learner's typed question is
echoed into the thread immediately (it is what the backend actually
stores, win or lose), and a failed question gets an inline error right
under it (`ChatMessage.isError`, same red-text convention as the word
popover's own `WordAnswer.isError`) rather than a page-level error -- the
question stays in the thread, asking again is just a new question. No
extra plumbing was needed to make typing in the chat count as reading
activity: the existing `pointerdown`/`keydown`/... listeners are already
on `document` (see "Active time" above), so a keystroke in the composer
already reaches them.

`ReadingScreen` also keeps the newest message scrolled into view as the
conversation grows -- a real gap the original (issue #9) shell never hit,
since no conversation before #11 ever grew past what fit on screen.
`sumi-side-panel`'s own scroll container (`.sumi-side-panel__body`) is in
*its* template, not `ReadingScreen`'s, so there is no local `viewChild` to
bind; a plain DOM query for it from an injected `ElementRef` works anyway
(only CSS scoping cares about that boundary, not a `querySelector`), run
from an `afterRenderEffect` that reads `chatMessages`/`chatSending` so it
reruns right after either one changes.

### History / Stats / Export (issue #12)

`pages/history`/`pages/stats` wire the approved presentational screens
(`features/history/`, `features/stats/`) to three read-only endpoints,
`api/stats.py`. Every statistic's actual maths is pure, in `app/
stats_math.py` -- no database, unit tested on its own in `tests/
test_stats_math.py` -- so `api/stats.py` is only the queries that turn
`reading_sessions`/`texts`/`help_events`/`topics` rows into that module's
`FinishedSessionStat` and back out as JSON (`tests/test_stats.py` covers
that wiring).

**`GET /api/history`** -- every session (any status), oldest first;
`HistoryScreen.rows` (frontend) reverses the list itself to show newest
first. A `reading`/`questions` row has `finished: false` and every number
(`speed_chars_per_minute`/`helps_per_100_words`/`comprehension_correct`/
`comprehension_total`) `null` -- the frontend shows "In progress" in their
place (`pages/history/history-mapping.ts`'s `toHistorySession`). Activating
a row navigates to `/read/<sessionId>` regardless of status -- the running
session or its summary, whichever `screenForStatus` resolves to. A text's
`topic_name` is its topic's own title by `topic_id` (the live FK), falling
back to the slug stored in `params.topic_slug` (prettied, `"daily-life"` ->
`"Daily life"`) once the topic itself is deleted (`ON DELETE SET NULL`).

**`GET /api/export`** -- every row the learner has ever generated or done
(`topics`/`texts`/`sessions`/`help_events`/`chat_messages`), flat, linked
only by the same foreign keys the tables themselves use. Unlike every other
response in this API, a text's `questions` here keep `answer_index` --
this is the learner's own data, not the reading UI, so there is no reason
to withhold it. The History page's "Export JSON" button downloads the
response as `jp-reading-practice-<today>.json` via a `Blob` + object URL
(`pages/history/history.ts`'s `exportData`, revoked right after the click).

**`GET /api/stats`** -- `summary` (and every series/bar/table below) is
`null`/empty together under `stats_math.STATS_MIN_SESSIONS` (3) finished
sessions, the existing empty state, never a partial page. Every constant
below is named and documented in `stats_math.py`, not repeated here --
only what each statistic *means*:

- **Speed** (字/min, `sumi-stat-tile`): median over the last 10 finished
  sessions (`SPEED_SAMPLE_SESSIONS`). Its delta is the *mean* over the last
  30 days vs. the 30 days before that, as a signed percent
  (`DELTA_WINDOW_DAYS`) -- `null` when either window has no finished
  session, never a divide-by-zero.
- **Helps/100 words** and **comprehension**: both over the last 10 finished
  sessions (`HELPS_SAMPLE_SESSIONS`) -- helps is that sample's median (same
  shape as speed), comprehension is *pooled* (total correct answers / total
  questions across the sample), never an average of per-session
  percentages, so one bad session does not get the same vote as one with
  three times as many questions.
- **Two trend charts** (speed, helps/100): the last 30 finished sessions
  (`SERIES_SAMPLE_SESSIONS`), oldest left, x label the session's
  `finished_at` day.
- **Reading level** (concept: "highest JLPT mix a learner reads
  comfortably"): a *text's* own level (`stats_math.text_level`) is the
  highest (hardest) JLPT level with a measured share >=
  `LEVEL_SHARE_THRESHOLD` (10%) in its `metrics.jlpt_mix`, N5 when none
  clears that bar. Per level, the last 5 finished sessions at that level
  (`READING_LEVEL_SAMPLE_SESSIONS`, needing at least 3,
  `READING_LEVEL_MIN_SESSIONS`) are **comfortable** when their median
  helps/100 is at or under 5 (`READING_LEVEL_HELPS_MAX`) *and* their pooled
  comprehension is at or above 80% (`READING_LEVEL_COMPREHENSION_MIN`), or
  **with help** when comprehension clears that bar but helps does not.
  `readingLevel` is the highest level found comfortable (`"—"` when none
  is yet); `readingLevelDetail` is `"comfortable"`, plus the next *higher*
  (harder) level's own "with help" status when it has one (e.g.
  `"comfortable · N3 with help"`) -- or, with no comfortable level at all,
  `"with help at <highest with-help level>"`, or `"not enough sessions per
  level yet"` when nothing qualifies either way (including a level with
  enough sessions that is simply struggling -- comprehension under 80% --
  which this message does not distinguish from "no data yet"; a known
  simplification, see `stats_math.reading_level`'s own docstring).
- **Speed by style** and **speed by topic** (two bar charts, the second a
  new section under the first): median 字/min per group
  (`stats_math.group_median_speed`), groups with >= 1 session, over *every*
  finished session (no recency window, unlike the headline numbers above).
  Style groups are ordered casual/polite/formal; topic groups
  alphabetically.
- **Problem words**: lemmas looked up (`word_lookup`) or explained
  (`explain`) in at least 2 different texts (`PROBLEM_WORD_MIN_TEXTS`),
  most-looked-up-first, top 20 (`PROBLEM_WORD_TOP_N`) -- reading is the
  lemma's own reading (never the surface's), meaning the first JMdict
  gloss, both resolved from the first `help_events` row seen for that
  lemma.
- **Stretch level** (issue #13, below): `d_after` over every adjustment,
  oldest first (`stretch_level_series`, a line chart, x = the adjustment's
  own date), plus the current resolved mix as one line of text
  (`stretch_now`, `stretch.describe_mix`). Both are `[]`/`null` together
  while Stretch has never adjusted yet, hiding the whole section -- gated,
  like every other Stats section, behind `get_stats`'s own
  `STATS_MIN_SESSIONS` check (`api/stats.py`'s `_stretch_level_section`).

### Stretch's adaptive difficulty (issue #13)

Stretch is one number, `d` (`app/stretch.py`), interpolated between four
anchor presets -- 0 (easy's own numbers), 1 (Stretch's pre-#13 static mix),
2 (challenge's own numbers), 3 (a fourth, harder-still anchor Stretch's own
adaptation only ever reaches *toward*):

| d | unknown kanji | N5 | N4 | N3 | N2 | N1 |
|---|---|---|---|---|---|---|
| 0 (easy) | 2 % | 70 | 30 | 0 | 0 | 0 |
| 1 (Stretch's start) | 5 % | 50 | 35 | 15 | 0 | 0 |
| 2 (challenge) | 10 % | 30 | 35 | 25 | 10 | 0 |
| 3 | 15 % | 15 | 30 | 30 | 20 | 5 |

`easy`/`challenge` call `stretch.interpolate()` at exactly `d=0`/`d=2` (so
their numbers match `presets.PRESETS` exactly, kept there unchanged as the
static table every preset -- including Stretch's own pre-#13 default --
still falls back to) -- only Stretch's own `d` ever moves. A mix in between
two anchors is linear interpolation, JLPT shares rounded to a whole percent
and always summing to exactly 100 (largest-remainder: each share's floor,
then the largest fractional remainders get the leftover point(s), ties
broken N5 before N4 before N3...); unknown kanji to one decimal percent.

**Stretch's own `d`** starts at `D_START` (1.0), clamped to `[D_MIN, D_MAX]`
= `[0.5, 2.5]`, stepping by `D_STEP` (0.1) per qualifying session. The rule
(`stretch.decide_reason`, pure, unit-tested in `tests/test_stretch.py`),
applied after a session finishes, only when its text was generated with
preset `stretch` and *no* JLPT-mix/unknown-kanji overrides
(`api/sessions.py`'s `_qualifies_for_stretch_adjustment`, reading the text's
own `params["preset"]`/`params["overrides_used"]` -- see "Generation"
below), and only on the text's *first* finished read (`_text_read_before`):
a re-read is easier for reasons that say nothing about the level, the same
reason the reading pace ignores re-reads:

- **harder** (`+D_STEP`): helps/100 words <= `HARDER_HELPS_MAX` (3) *and*
  comprehension >= `HARDER_COMPREHENSION_MIN` (80%).
- **easier** (`-D_STEP`): helps/100 words > `EASIER_HELPS_MIN` (8) *or*
  comprehension < `EASIER_COMPREHENSION_MAX` (60%).
- otherwise **unchanged** -- still its own row (see below), `d` untouched.

**`stretch_adjustments`** (`db.py`, one Alembic revision, `0006`): `id`,
`session_id` (unique FK, `ON DELETE CASCADE`), `d_before`, `d_after`,
`helps_per_100_words`, `comprehension`, `reason`
(`harder`/`easier`/`unchanged`), `created_at`. The unique `session_id` is
the idempotency itself (`ON CONFLICT DO NOTHING`,
`app/stretch_store.record_adjustment`, same convention `help_events` uses)
-- inserted in the exact same transaction that flips a session to
`finished` (the last answer, `api/sessions.py`'s `answer_question`).
Stretch's *current* `d` is simply the latest row's `d_after`
(`stretch_store.current_d`), else `D_START` when the table is empty.
`app/stretch.py` is the pure maths (interpolation, the rule), `app/
stretch_store.py` the only module touching the table, `api/sessions.py`/
`api/texts.py`/`api/presets.py` the HTTP-layer glue -- same three-way split
`stats_math.py`/`api/stats.py` already uses.

**Generation.** `POST /api/texts` with preset `stretch` resolves its
(pre-override) numbers at the *current* `d` (`api/texts.py`'s
`_resolve_targets`, `stretch_store.current_d` -> `stretch.resolve`) --
overrides still win per field, exactly as before #13. The stored
`texts.params` records both the resolved `TextTargets` and, for a stretch
text, the `d` they were resolved at (`"stretch_d"`) plus, for *every* text
regardless of preset, which fields were overridden
(`"overrides_used": {"unknown_kanji_target": bool, "jlpt_mix": bool}`) --
extra keys `TextTargets.model_validate(row.params)` (`_text_out`) simply
ignores, so neither ever reaches the browser's own `targets` shape. This is
exactly what `_qualifies_for_stretch_adjustment` reads back.

**`GET /api/presets`** (`api/presets.py`) -- the three presets' resolved
values: `easy`/`challenge` straight from the static `presets.PRESETS`,
`stretch` resolved at its current `d` (plus `d` itself and the last
adjustment's own `reason`/`created_at`, `null` before the first one). The
setup screen (`pages/read/read.ts`) reads this instead of its own
hard-coded `setup.types.ts`'s `DIFFICULTY_PRESETS` table for the preset
descriptions and the "Adjust" defaults, refreshing the *currently selected*
preset's numbers once it loads (only for a field not already touched via
"Adjust") -- `DIFFICULTY_PRESETS` stays as the offline fallback and the
`/preview` fixtures' own data, exactly as the brief asked.

**The summary's one quiet line** (`GET /api/sessions/{id}/summary`'s
`stretch_adjustment`, `"harder"`/`"easier"`/`null` -- never `"unchanged"`,
which still gets its own `stretch_adjustments` row but nothing worth
reading about) becomes "Stretch is now a little harder."/"...a little
easier." via `pages/read/stretch-note.ts`'s `stretchNoteText` (pure, unit
tested), shown under the summary tiles (`SummaryScreen.stretchNote`).

### AI suggestion for the next text (issue #14)

A secondary button on the setup screen, **"Suggest next text"**, above the
topic picker -- while it runs the button shows "Thinking…" and is disabled;
the result (or an error) appears as a small card in the same place, never a
separate page, and nothing here ever suggests automatically.

**`POST /api/suggestions`** (`app/api/suggestions.py`) -> `{id, topic_slug,
length, preset, overrides | null, reason}` (`models.SuggestionOut`). One
Structured-Outputs chat completion against `RuntimeConfig.help_model` --
the same slot the three LLM helps/tutor chat use (`app/assist.py`), not
`generation_model`: this is a short judgement call over a compact context,
not a full text. Same 409 (no key)/502 (upstream, refusal, empty, unusable
JSON) convention as every other OpenAI call in this app
(`generation.GenerationError`).

**The context** (`app/suggestion_prompts.py`'s `SuggestionContext`,
assembled by `api/suggestions.py`'s `_build_context` -- pure dataclasses in,
no I/O, so the prompt itself is unit-tested from hand-built values with no
database at all): every topic's slug/title/style/news-backed-or-not
(`feed_urls` non-empty, issue #15's own convention); the last 10 *finished*
sessions, newest first (date, topic, length, preset, style, the text's own
JLPT level via `stats_math.text_level`, 字/min, helps/100 words,
comprehension) -- fewer than 3 finished sessions ever, and the prompt says
so instead and asks for a gentle, welcoming start; the Stats page's own
reading level/detail and speed trend (`stats_math.compute_summary`, gated
behind its own `STATS_MIN_SESSIONS` the same way `GET /api/stats` is);
Stretch's current resolved mix and `d` (`stretch_store.current_d` ->
`stretch.resolve`); days since the last session of any status (`None` for
"never read before"); and a one-word time of day
(`suggestion_prompts.time_of_day_label`) from the browser's own hour
(`POST /api/suggestions {local_hour}`; the server's clock is usually UTC in
its container), falling back to the server hour when none is sent.

**The prompt's rules** (`suggestion_prompts._RULES`): vary topics -- avoid
both of the last two read, unless the learner keeps choosing the same one
or two on purpose, in which case that repetition itself is the evidence to
follow; move difficulty only one preset step at a time (easy/stretch/
challenge, never skip one); prefer a plain preset over overrides, adding one
only when the evidence above gives it a clear, specific reason; never
suggest the topic `"surprise"`; the reason must name the concrete evidence
behind the pick, in 1-2 plain English sentences.

**Validation/clamping** (`app/suggestions.py`, server-side, after Structured
Outputs already forced the shape): `topic_slug` must be one of the live
topics' own slugs -- an unknown slug *or* `"surprise"` (never a real row) is
the same 502, `validate_topic_slug`'s one check covers both. Overrides are
clamped, never rejected outright: `unknown_kanji_target_percent` into the
setup screen's own slider range (`setup.types.ts`/`setup-screen.html`,
0-20%, `clamp_unknown_kanji_target_percent`); `jlpt_mix_percent` normalised
to sum to exactly 100 in 5-point steps by scaling then largest-remainder
rounding (`normalize_jlpt_mix_percent`, same tie-break N5-first as
`stretch._round_mix_percent`) -- *dropped* (not included in the stored
overrides at all) when it cannot be normalised into something sane: any
level negative, or everything zero. `resolve_overrides` returns `None`
overrides entirely once every field has been dropped, so a suggestion that
gave weak overrides quietly falls back to "prefer the plain preset".

**The schema** (`app/suggestions.py`'s `SuggestionSchema`, via
`generation._strict_schema`, the same OpenAI Structured-Outputs tightening
`generation.py`'s own `GeneratedTextSchema` uses): `topic_slug`, `length`,
`preset` (the same three `Literal`s `TextCreateRequest` uses), `overrides`
(nullable -- `style`/`unknown_kanji_target_percent`/`jlpt_mix_percent`, the
model's own percent-space guess, converted to `SuggestionOverridesOut`'s
fraction convention only after clamping above), `reason`.

**Stored** (`suggestions` table, Alembic `0008`): `id`, `created_at`,
`payload` JSON (the validated/clamped suggestion exactly as the browser
received it), `reason` (duplicated as its own column, purely so it can be
read without unpacking the JSON), `model`, `usage`, `cost_usd`
(`pricing.cost_usd`, `None` for a model the rate table does not know, same
convention as `GeneratedText.cost_usd`), `used_text_id` (nullable FK to
`texts.id`, `ON DELETE SET NULL`).

**`POST /api/texts`** accepts an optional `suggestion_id`
(`TextCreateRequest.suggestion_id`) and marks that suggestion's
`used_text_id` once the text is created (`api/texts.py`'s
`_mark_suggestion_used`) -- but only when `topic_slug`/`length`/`preset` on
this request still match the suggestion's own `payload` exactly; a learner
who changed any of the three before generating did not "use" it, per the
brief, and the field is silently ignored (never a failed generation) for a
missing or already-used suggestion id.

**Frontend** (`features/read/setup/`): `SetupScreen` gains `suggesting`/
`suggestion`/`suggestionError` inputs and `suggestNext`/`useSuggestion`/
`dismissSuggestion` outputs, fully presentational like every other control
on this screen -- `ReadPage` (`pages/read/read.ts`) owns the actual
`Api.suggestNext()` call and the applied state. "Use this"
(`suggestion-apply.ts`'s pure `applySuggestionToSetup`, unit tested on its
own) sets topic/length/preset and -- only for a field the suggestion
actually overrode -- the matching "Adjust" control, opening "Adjust" exactly
when at least one of them is set; it never calls `createText()` itself (the
brief: applies, does not generate). `ReadPage` remembers the suggestion's
`id` (`appliedSuggestionId`) and sends it as `suggestion_id` on the next
`POST /api/texts`, clearing it the moment the learner changes topic, length
or preset by hand -- the same "did not use it" rule the backend re-checks
regardless. An error (409/502) shows inline in the card's own place
(`hint--error`, `var(--sumi-wrong)`), the same convention the word popover's
helps use for theirs.

### Current events: RSS / web-search material (issue #15)

A topic is **news-backed** simply by having `feed_urls` (`Topic.feed_urls`,
a JSON list, editable in the Topics screen for *every* topic, not just
Current events) -- the default seeded for Current events is NHK News Web,
`https://www.nhk.or.jp/rss/news/cat0.xml` (`backend/topics/
03-current-events.md`; the *old* `www3.nhk.or.jp` URL this app originally
shipped with froze in mid-2026, still answering 200 with two-month-old
`pubDate`s -- the freshness filter below exists specifically so a frozen
feed like that degrades loudly instead of quietly feeding stale headlines
into a text). `seed_topics`'s existing "skip a customized row" rule covers
`feed_urls` the same as every other seeded field -- changing the shipped
URL here still reaches an untouched install on its next boot, never a
topic someone has edited.

**The material step** (`app/news.py`, called from `generation.generate_text`
via its own `_gather_material`) runs before the generation call, only for a
news-backed topic -- a topic with no feeds behaves exactly as it did before
this issue, with no `# Material` prompt section and no stored `source`/
`material_error` at all. Two paths, chosen by the existing
`RuntimeConfig.web_search_enabled` Settings toggle:

- **RSS (default)**: every feed URL on the topic, fetched with `httpx`
  (10s timeout, redirects followed, a real browser User-Agent -- NHK and
  most Japanese news sites 403 a bare `python-httpx/...` one) and parsed
  with `defusedxml`. RSS 2.0, RDF/RSS 1.0 and Atom are all handled by the
  *same* pass over the tree, matching `<item>`/`<entry>` by local element
  name regardless of namespace (`news._parse_feed_items`) -- the three
  formats differ in element names, not in overall shape. An item's date is
  `pubDate`/`dc:date` (RFC 822) or Atom's `published`/`updated` (ISO 8601);
  an item with no date of its own is kept only if the *feed's* own
  channel-level date (`lastBuildDate`/`pubDate`/`dc:date`/`updated`,
  `news._feed_own_date`, read only from `channel`'s or the root's *direct*
  children, never an item's own same-named field) is itself within
  `FRESHNESS_WINDOW` (3 days) -- this is the frozen-feed case above: every
  item on a feed that stopped publishing is older than 3 days, so the
  whole feed reports "nothing fresh" rather than silently passing old
  headlines through. Merged across every feed on the topic, newest first,
  top 5 (`MAX_ITEMS`). One feed failing (down, malformed XML) does not fail
  the others; `MaterialResult.error` is only set when *nothing* fresh came
  back from any feed, naming either the fetch failures or "nothing fresh"
  depending on which happened. Cached in-process per URL, 15 minutes
  (`news._feed_cache`, `news.clear_cache()` for tests -- same shape as
  `kanji_trainer.py`'s own cache).
- **Web search (opt-in)**: for a news-backed topic only, instead of RSS,
  one OpenAI **Responses API** call (`POST /responses`, not
  `/chat/completions`) with the built-in `web_search` tool, asking for 3-5
  current Japanese items about the topic as structured JSON (`text.format`
  `json_schema`, the Responses API's own equivalent of Chat Completions'
  `response_format`) -- `RuntimeConfig.generation_model` either way, so
  switching the toggle never introduces a second configured model. The
  call's own token usage (`usage.input_tokens`/`output_tokens`/
  `input_tokens_details.cached_tokens`, confirmed against
  developers.openai.com's Responses API reference, 2026-10-18) is billed at
  that model's normal chat rate and folded straight into the text's own
  `calls`/`usage`; the tool's *own* flat per-call fee
  (`pricing.web_search_cost_usd`, $10.00/1k calls -- see `pricing.py`'s own
  citation) is kept separate as `GenerationOutcome.extra_cost_usd`, added on
  top of `pricing.cost_usd()` for the stored `cost_usd` (`api/texts.py`'s
  `create_text`) rather than folded into the per-token maths, since it is
  not a token cost at all. A model that does not support the tool raises
  `news.WebSearchUnsupported` (detected from the HTTP 400/404 body
  mentioning `web_search`), which `generate_text` turns into a
  `material_error` naming the model -- the same degrade-with-a-reason shape
  every other material failure gets, not a failed generation.

**The prompt** (`prompts.py`'s `_material_section`, called from
`build_generation_instructions`) adds a `# Material` section right after
`# Topic`, in one of three shapes: real items to retell (title/summary/date
only, deliberately never the URL -- `prompts.MaterialItem` has no `link`
field at all, so there is nothing to leak), the neutral invented-news
fallback (the "write a plausible, generic... never use real names" wording
`topics/03-current-events.md` used to carry itself, now generated by the
frame so it applies no matter *why* the material went missing) when
`material_error` is set instead, or nothing at all for a topic with no
feeds. The structured output (`generation.GeneratedTextSchema`) gains
`source_index` (which listed item, 0-based, the text retold) -- Structured
Outputs' strict mode forces the model to return *some* integer here even
for a topic with no material, where it is simply never read; an
out-of-range index (the model ignoring the instruction) falls back to item
0 rather than losing the attribution entirely. `test_prompts.py` has the
same "a malicious topic/material string cannot remove the frame's own
rules" snapshot-style tests the rest of the prompt already had, extended to
a material item's own title.

**Stored** (`texts.source`/`texts.material_error`, Alembic revision `0007`):
`source` is `{title, link, published, via: "rss"|"web_search"}` for the one
material item retold, `null` for a topic with no feeds and for one whose
material fetch failed; `material_error` is the English reason for the
latter, `null` otherwise -- reported the same way
`known_snapshot["kanji_trainer_error"]` already is (generation still
happens, just with the fallback line, and the reason rides alongside the
row rather than failing the request). `TextOut`/`TextSourceOut` (`models.py`)
carry both to the browser.

**Frontend**: `pages/read/source-line.ts`'s pure `sourceLineFor` (unit
tested, `source-line.spec.ts`) turns a `TextOutApi.source` into "Source:
<title> ↗" (`ReadingTextData.source`/`SummaryScreen.source`, both the same
`SourceLine` shape from `features/read/reading/reading.types.ts`) -- shown
as a quiet link (`target="_blank" rel="noopener"`) right under the reading
screen's last paragraph, above "Done reading", and again on the summary;
`null` renders neither. `GateScreen.materialErrorNote` (optional, default
`null`, same pattern as the pre-existing `kanjiTrainerErrorNote`) shows
`material_error` as a second `sumi-banner` notice on the gate. The Topics
editor's RSS feeds field (`TopicEditScreen.showRssFeeds`) is shown for
*every* topic now, not only Current events -- any topic becomes
news-backed simply by having at least one feed URL; its placeholder/hint
name the current NHK URL and explain what adding a feed does. Settings'
existing web-search toggle gets one more hint line: "Current events use web
search instead of RSS feeds; adds the search cost to each text."

### Readable OpenAI error messages

Every OpenAI call (`generation.py`, `assist.py`, `suggestions.py`, and
`news.py`'s web-search material path) turns an `httpx.HTTPStatusError`/
`httpx.HTTPError` into a message via `app/openai_errors.py`'s
`describe_openai_error()`, rather than formatting `exc.response.text`
itself -- that raw body is a JSON blob meant for a developer, not a
learner, and used to reach the browser verbatim through
`GenerationError`'s message and the frontend's "The server refused:"
prefix. The helper parses the body's `error.message`/`error.code`/
`error.type` when present and maps the common cases to one plain English
sentence each (401 -> bad key, 429/quota -> rate limit or billing, 5xx ->
transient, `model_not_found` -> names the configured model, a timeout or
connection error -> its own sentence); anything else falls back to the
upstream's own `error.message` (never the raw body), prefixed
"OpenAI returned an error:". The raw body is only ever `logger.warning`'d,
tagged with a short `context` string naming the call site -- never
returned. **Add a new OpenAI call site through this helper, not a new
f-string.**

The frontend's `core/api.ts` `rethrow()` shows a 409/502 `detail` as-is,
with no "The server refused:" lead-in -- those two statuses are exactly
what `GenerationError`'s own 409 (no key)/502 (upstream) convention uses,
so `detail` there is already one of the helper's complete sentences (or
one of the handful of other 409s, e.g. "no topics to suggest from", which
read fine unprefixed too). Every other status keeps the lead-in.

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

- No authentication. Single user, LAN only -- the same assumption the other
  stacks make.
