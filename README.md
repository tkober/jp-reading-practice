# JP Reading Practice

A Japanese reading practice app: LLM-generated texts at the learner's level,
built on the vocabulary knowledge the other apps in the suite already have
(chiefly [Kanji Trainer](https://github.com/tkober/kanji-trainer)). See
`REQUIREMENTS.md` for the full concept.

Clone with submodules -- the frontend's Sumi UI library is a git submodule:

```bash
git clone --recurse-submodules https://github.com/tkober/jp-reading-practice.git
# or, in an existing checkout:
git submodule update --init
```

Currently the FastAPI backend skeleton (issue #2) and the Angular frontend
skeleton (issue #3) -- no domain logic and no deployment yet. See `CLAUDE.md`
for how to run both.

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm ci
npm start   # proxies /api to :8000, see proxy.conf.json
```

Or both together: `./dev.sh` (needs `backend/.env`, copied from
`backend/.env.example`).
