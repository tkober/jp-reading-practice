# JP Reading Practice

A Japanese reading practice app: LLM-generated texts at the learner's level,
built on the vocabulary knowledge the other apps in the suite already have
(chiefly [Kanji Trainer](https://github.com/tkober/kanji-trainer)). See
`REQUIREMENTS.md` for the full concept.

Currently just the FastAPI backend skeleton (issue #2) -- no frontend, no
deployment and no domain tables yet. See `CLAUDE.md` for how to run it.

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```
