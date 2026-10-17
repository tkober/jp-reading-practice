"""JMdict lookup for the word popover (issue #7).

The dictionary itself is built by `scripts/build_jmdict.py` into
`app/data/jmdict.sqlite` -- see that script and `app/data/LICENSES.md` for
where the data comes from and why it is not committed. This module only
reads it: a single read-only connection, opened lazily and kept open for the
process's lifetime (SQLite handles concurrent readers fine, and there is
never a writer outside the build script).

Missing gracefully: a backend that has not had the dictionary built yet (a
fresh checkout before the one-time `uv run python scripts/build_jmdict.py`)
must still serve `/api/analysis` -- just without dictionary entries, the
same shape of degradation `kanji_trainer.py`'s `KanjiTrainerUnavailable`
is for the known set and JLPT levels. `lookup()` returns `None` in that case
rather than raising.
"""

from __future__ import annotations

import logging
import sqlite3
from functools import lru_cache
from pathlib import Path

from .models import DictionaryEntry

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent / "data" / "jmdict.sqlite"


@lru_cache(maxsize=1)
def _connection() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        logger.warning(
            "Dictionary disabled: %s does not exist -- run "
            "`uv run python scripts/build_jmdict.py` (from backend/) to build it.",
            DB_PATH,
        )
        return None
    # Read-only: nothing here ever writes, and the build script replaces the
    # whole file rather than updating it in place.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)


def lookup(lemma: str, reading: str) -> DictionaryEntry | None:
    """One JMdict sense group for an exact lemma+reading match, or `None`
    when the dictionary has not been built or the pair is not in it."""
    connection = _connection()
    if connection is None:
        return None

    row = connection.execute(
        "SELECT lemma, reading, pos, glosses FROM entries WHERE lemma = ? AND reading = ?",
        (lemma, reading),
    ).fetchone()
    if row is None:
        return None

    lemma_out, reading_out, pos, glosses = row
    return DictionaryEntry(
        lemma=lemma_out,
        reading=reading_out,
        pos=[p.strip() for p in pos.split(",") if p.strip()],
        glosses=[g.strip() for g in glosses.split(";") if g.strip()],
    )
