"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str
    database: bool


# --- Settings ----------------------------------------------------------------


class SettingsIn(BaseModel):
    """Patch for the settings row.

    Every field is optional: omitting one leaves it unchanged. Sending an
    empty string (or ``null``) clears the override so the environment default
    applies again.
    """

    openai_api_key: str | None = None
    generation_model: str | None = None
    help_model: str | None = None
    kanji_trainer_mcp_url: str | None = None
    web_search_enabled: bool | None = None


class SettingsOut(BaseModel):
    """The effective settings, safe to send to the browser.

    The OpenAI key is never returned in full -- only whether one is set, a
    masked hint, and whether it came from the environment.
    """

    generation_model: str
    help_model: str
    kanji_trainer_mcp_url: str
    web_search_enabled: bool

    openai_api_key_set: bool
    openai_api_key_hint: str | None = None
    openai_api_key_from_env: bool


# --- Kanji Trainer MCP ---------------------------------------------------


class KanjiTrainerStatus(BaseModel):
    """What the Settings screen's "Test connection" button shows.

    Always HTTP 200 -- this reports the connection's state, it is not itself
    failing when kanji-trainer is unreachable. `level`/`known_kanji`/
    `known_vocabulary` are `None` exactly when `reachable` is `False`.
    """

    reachable: bool
    url: str
    level: int | None = None
    known_kanji: int | None = None
    known_vocabulary: int | None = None
    error: str | None = None


# --- Text analysis (issue #7) -------------------------------------------

# A word's JLPT level, 5 = N5 (easiest) .. 1 = N1 (hardest), same convention
# kanji_trainer.py and kanji-trainer's own MCP server use throughout --
# `None` for a word/kanji the JLPT snapshot does not list.


class RubySegment(BaseModel):
    """One piece of a word, with its reading when it contains kanji.

    ``base`` is always a verbatim slice of the word's surface, so the
    segments joined together are the surface again. Field names match
    sumi-ui's `sumi-furigana` component (`{ base, reading }`), which #9 is
    expected to feed these into directly -- see
    `tappable-ruby-text.ts` on `feature/design-6`.
    """

    base: str
    reading: str | None = None


class KanjiInfo(BaseModel):
    """One kanji occurring in a token, with its own JLPT level and known
    state -- independent of the word around it, since a kanji's own
    "known"-ness does not depend on which word it appears in."""

    character: str
    jlpt: int | None = None
    known: bool


class Token(BaseModel):
    """One morpheme from the tokenizer, annotated with everything the
    reading UI (#9) and the measuring logic (#8) need.

    ``lemma`` is the dictionary form used for vocabulary/JLPT lookups (see
    `analysis.py`'s `_lemma_for` for why it is not always unidic's own
    ``lemma`` feature); ``surface``/``reading``/``segments`` describe the
    word exactly as it appears in the text.
    """

    id: str
    surface: str
    lemma: str
    reading: str
    pos: str
    segments: list[RubySegment]
    jlpt: int | None = None
    kanji: list[KanjiInfo] = Field(default_factory=list)
    known_word: bool
    needs_furigana: bool
    is_word: bool


class Paragraph(BaseModel):
    tokens: list[Token]


class JlptMix(BaseModel):
    """Share (0..1) of content words at each JLPT level, see
    `analysis.py`'s `_jlpt_mix` -- the five shares plus `unlisted` sum to 1
    unless there are no content words at all, in which case every share is 0.
    """

    n5: float = 0.0
    n4: float = 0.0
    n3: float = 0.0
    n2: float = 0.0
    n1: float = 0.0
    unlisted: float = 0.0


class Metrics(BaseModel):
    #: Kana + kanji + latin letters/digits in the raw text -- no punctuation
    #: or whitespace. What "characters per minute" is measured against.
    characters: int
    #: Tokens with `is_word` (see `Token`) -- what "helps per 100 words" is
    #: measured against.
    words: int
    #: Kanji occurrences across every token (not distinct characters).
    kanji_total: int
    #: Occurrences of a kanji the learner does not yet know.
    kanji_unknown: int
    unknown_kanji_share: float
    jlpt_mix: JlptMix = Field(default_factory=JlptMix)


class TextAnalysis(BaseModel):
    paragraphs: list[Paragraph]
    metrics: Metrics


class AnalysisRequest(BaseModel):
    text: str


class AnalysisResponse(TextAnalysis):
    """`POST /api/analysis`'s response -- `TextAnalysis` plus, only when the
    Kanji Trainer could not be reached, the English reason why the known set
    and JLPT levels are missing from the analysis above."""

    kanji_trainer_error: str | None = None


class DictionaryEntry(BaseModel):
    """One JMdict sense group for a lemma+reading, for the word popover."""

    lemma: str
    reading: str
    pos: list[str] = Field(default_factory=list)
    glosses: list[str] = Field(default_factory=list)
