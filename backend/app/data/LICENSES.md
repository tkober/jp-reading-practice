# Third-party data

## JMdict (word popover: readings, part of speech, English glosses)

`jmdict.sqlite` in this directory is built from **JMdict_e**, the
English-only edition of JMdict, by `backend/scripts/build_jmdict.py`. It is
not committed here -- see that script's module docstring for why, and
`.gitignore` -- and has to be built once by hand in development
(`uv run python scripts/build_jmdict.py`, from `backend/`) and again by
`backend/Dockerfile`'s builder stage on every image build.

JMdict is the property of the Electronic Dictionary Research and
Development Group (EDRDG) at Monash University, and is used here under the
[Creative Commons Attribution-ShareAlike Licence (V4.0)][licence]:

> This work is based on the JMdict, JMnedict, and KANJIDIC2 dictionary
> files, which are the property of the Electronic Dictionary Research and
> Development Group, and are used in conformance with the Group's licence.

Project home: <https://www.edrdg.org/jmdict/j_jmdict.html>. Downloaded from
<http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz>.

[licence]: https://www.edrdg.org/edrdg/licence.html

## JLPT levels

JLPT levels shown throughout this app (`Token.jlpt`, `KanjiInfo.jlpt`,
`Metrics.jlpt_mix`) are **not** stored here -- they come from the Kanji
Trainer's own MCP tool `get_jlpt_levels` at request time (see
`app/kanji_trainer.py` and this repo's `CLAUDE.md`, "Text analysis"). That
app's own `backend/app/data/jlpt/` carries the tanos-list attribution for
the snapshot it serves; nothing here duplicates it.
