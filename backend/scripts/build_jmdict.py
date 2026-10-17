#!/usr/bin/env python3
"""Build the local JMdict dictionary SQLite (issue #7's word popover).

JMdict (The Electronic Dictionary Research and Development Group, EDRDG,
CC BY-SA 4.0 -- see `../app/data/LICENSES.md`) is the practical choice here:
it is a single, actively maintained file covering essentially every word a
generated text could contain, with readings, part-of-speech tags and English
glosses in one place -- exactly what the word popover needs, and nothing
this app would otherwise have to assemble from several sources. The
alternative considered was a PyPI package that bundles JMdict as a ready-made
SQLite (e.g. `jamdict`); it was not used because it pulls in its own larger
database (~100 MB, including example sentences and a kanji dictionary this
app does not need) where downloading the ~10 MB source file and keeping only
the few MB this app actually uses is both smaller and auditable -- this
script *is* the transformation, rather than a dependency's opaque build.

Usage::

    uv run python scripts/build_jmdict.py

Downloads ``JMdict_e.gz`` from EDRDG's own FTP mirror (the "English-only"
edition -- no point shipping every other language's glosses), parses it
with a streaming ``ElementTree.iterparse`` (XML's internal DTD entities,
e.g. ``&v1;`` -> "Ichidan verb", are resolved by the parser itself -- no
special handling needed, see the module docstring of `app/dictionary.py`),
and writes a compact SQLite to ``app/data/jmdict.sqlite``: lemma, reading,
part-of-speech tags and the first three English glosses per entry, nothing
else -- no example sentences, no cross-references, no the dozen other
annotation fields JMdict carries. That keeps the result at roughly a tenth
of the source file's size (see the printed summary) and is why the file is
gitignored and built here rather than committed: it is a derived artefact,
not something to track changes on and it would be a large binary.

Run once by a developer (this environment: no Docker, so this runs directly
against the local checkout) and again by `backend/Dockerfile`'s builder
stage at image build time -- see that file's comment on why it is a
separate stage.
"""

from __future__ import annotations

import gzip
import sqlite3
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

JMDICT_URL = "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz"

DATA_DIR = Path(__file__).resolve().parent.parent / "app" / "data"
DOWNLOAD_PATH = DATA_DIR / "JMdict_e.gz"
DB_PATH = DATA_DIR / "jmdict.sqlite"

#: Only the first sense's English glosses count towards "first 3" -- the
#: popover shows a short summary, not every sense a word has ever had.
MAX_GLOSSES = 3


def _download(path: Path) -> None:
    print(f"Downloading {JMDICT_URL} -> {path}")
    with urllib.request.urlopen(JMDICT_URL, timeout=60) as response:  # noqa: S310 - fixed, trusted URL
        path.write_bytes(response.read())


def _readings_for_keb(keb: str, r_eles: list[ET.Element]) -> list[str]:
    """Readings that apply to this kanji form -- all of them, unless an
    `r_ele` restricts itself to specific kanji forms via `re_restr`."""
    readings = []
    for r_ele in r_eles:
        restrictions = [el.text for el in r_ele.findall("re_restr")]
        if restrictions and keb not in restrictions:
            continue
        reb = r_ele.findtext("reb")
        if reb:
            readings.append(reb)
    return readings


def _entries(xml_path: Path) -> "list[tuple[str, str, str, str]]":
    """Parse the JMdict XML into `(lemma, reading, pos, glosses)` rows.

    One row per lemma/reading pair -- an entry with several kanji forms and
    several readings fans out into every combination its own `re_restr`
    (reading restriction) elements allow, which is almost always "every
    form with every reading" since restrictions are the exception.
    """
    rows: list[tuple[str, str, str, str]] = []
    count = 0
    with gzip.open(xml_path, "rb") if xml_path.suffix == ".gz" else open(xml_path, "rb") as fh:
        for event, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag != "entry":
                continue
            count += 1

            senses = elem.findall("sense")
            first_sense = senses[0] if senses else None
            first_pos = first_sense.findall("pos") if first_sense is not None else []
            pos_tags = list(dict.fromkeys(p.text for p in first_pos if p.text))
            glosses: list[str] = []
            for sense in senses:
                for gloss in sense.findall("gloss"):
                    # Only unlabelled (= English) glosses -- JMdict_e already
                    # carries only English, but a `lang` attribute would mark
                    # a different language if that ever changed upstream.
                    if gloss.get("{http://www.w3.org/XML/1998/namespace}lang") not in (None, "eng"):
                        continue
                    if gloss.text:
                        glosses.append(gloss.text)
                    if len(glosses) >= MAX_GLOSSES:
                        break
                if len(glosses) >= MAX_GLOSSES:
                    break

            r_eles = elem.findall("r_ele")
            k_eles = elem.findall("k_ele")
            pos_text = ", ".join(pos_tags)
            glosses_text = "; ".join(glosses)

            if k_eles:
                for k_ele in k_eles:
                    keb = k_ele.findtext("keb")
                    if not keb:
                        continue
                    for reading in _readings_for_keb(keb, r_eles):
                        rows.append((keb, reading, pos_text, glosses_text))
            else:
                # Kana-only entries (no k_ele at all): the reading stands in
                # for the lemma too, so a kana-only word can still be looked
                # up by its own text.
                for r_ele in r_eles:
                    reading = r_ele.findtext("reb")
                    if reading:
                        rows.append((reading, reading, pos_text, glosses_text))

            elem.clear()
            if count % 50_000 == 0:
                print(f"  ...{count} entries parsed")

    print(f"Parsed {count} JMdict entries -> {len(rows)} lemma/reading rows")
    return rows


def _write_sqlite(rows: list[tuple[str, str, str, str]], db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE entries ("
            "lemma TEXT NOT NULL, reading TEXT NOT NULL, pos TEXT NOT NULL, "
            "glosses TEXT NOT NULL, PRIMARY KEY (lemma, reading))"
        )
        # INSERT OR IGNORE: a handful of (lemma, reading) pairs recur across
        # distinct JMdict entries (e.g. a word and its abbreviation sharing
        # a reading) -- the first one parsed wins, which is good enough for
        # a popover summary rather than a scholarly merge of every sense.
        conn.executemany(
            "INSERT OR IGNORE INTO entries (lemma, reading, pos, glosses) VALUES (?, ?, ?, ?)",
            rows,
        )
        # No separate index on `lemma` alone: the `(lemma, reading)` primary
        # key is already a lemma-first btree, so a lookup by lemma alone (no
        # reading) is already an efficient prefix scan of it.
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DOWNLOAD_PATH.exists():
        _download(DOWNLOAD_PATH)
    else:
        print(f"Reusing already-downloaded {DOWNLOAD_PATH}")

    started = time.monotonic()
    rows = _entries(DOWNLOAD_PATH)
    _write_sqlite(rows, DB_PATH)
    elapsed = time.monotonic() - started

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"Wrote {DB_PATH} ({size_mb:.1f} MiB) in {elapsed:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
