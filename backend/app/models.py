"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    #: The *lemma's* own reading (`RawToken.lemma_reading`, unidic's
    #: `kanaBase` folded to hiragana) -- unlike `reading` above (the
    #: surface's own reading, for ruby display), this is what issue #9's
    #: word lookup shows and looks the dictionary up by, so a conjugated
    #: surface (e.g. 食べました) names its dictionary form's reading
    #: (たべる) rather than its own (たべました). Defaults to `""` so a
    #: `texts` row stored before this field existed still deserialises.
    lemma_reading: str = ""
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


# --- Topics (issue #8) -------------------------------------------------------

TopicStyle = Literal["casual", "polite", "formal"]


class TopicOut(BaseModel):
    """One topic, as the Topics list/editor sees it."""

    id: int
    slug: str
    title: str
    glyph: str
    prompt: str
    default_style: TopicStyle
    feed_urls: list[str] = Field(default_factory=list)
    sort_order: int
    is_builtin: bool
    is_customized: bool


class TopicCreate(BaseModel):
    """A new custom topic. Always `is_builtin=False`, `is_customized=True` --
    there is nothing to "reset" a topic nobody shipped a file for."""

    title: str
    glyph: str = ""
    prompt: str
    default_style: TopicStyle = "casual"
    feed_urls: list[str] = Field(default_factory=list)


class TopicUpdate(BaseModel):
    """Patch for a topic. Every field optional: omitting one leaves it
    unchanged. Saving always marks the row `is_customized` (see
    `api/topics.py`)."""

    title: str | None = None
    glyph: str | None = None
    prompt: str | None = None
    default_style: TopicStyle | None = None
    feed_urls: list[str] | None = None


# --- Text generation (issue #8) ----------------------------------------------


class JlptMixTarget(BaseModel):
    """Target share (0..1) of content words at each JLPT level -- the
    preset's (or caller's) *target*, as opposed to `Metrics.jlpt_mix`'s
    *measured* share of the same shape."""

    n5: float = 0.0
    n4: float = 0.0
    n3: float = 0.0
    n2: float = 0.0
    n1: float = 0.0


class TextOverrides(BaseModel):
    """Free-form overrides on top of a preset -- every field optional."""

    style: TopicStyle | None = None
    unknown_kanji_target: float | None = None
    jlpt_mix: JlptMixTarget | None = None


class TextCreateRequest(BaseModel):
    """`POST /api/texts`'s body.

    `topic_slug` is either a real topic's slug, or the literal `"surprise"`
    sentinel, which picks a random topic at generation time (the stored
    text then names the topic it actually landed on -- see `targets` below).
    """

    topic_slug: str
    length: Literal["short", "medium", "long"]
    preset: Literal["easy", "stretch", "challenge"]
    overrides: TextOverrides | None = None


class QuestionOut(BaseModel):
    """A comprehension question, without its answer -- `answer_index` never
    reaches the browser; issue #9 checks answers server-side instead."""

    question: str
    options: list[str] = Field(default_factory=list)


class TextTargets(BaseModel):
    """What generation was actually asked for, after resolving the preset,
    the topic's own default style, and any overrides -- `topic_slug` is the
    *resolved* topic (never `"surprise"` itself)."""

    topic_slug: str
    length: Literal["short", "medium", "long"]
    preset: Literal["easy", "stretch", "challenge"]
    unknown_kanji_target: float
    jlpt_mix: JlptMixTarget
    style: TopicStyle


class TextOut(BaseModel):
    """`POST /api/texts` and `GET /api/texts/{id}`'s response.

    `paragraphs` are the stored `TextAnalysis.paragraphs` (full analysis
    tokens, as of generation, for the reading screen to render directly);
    `metrics` are the *measured* numbers for the same text, as opposed to
    `targets`, what was asked for.
    """

    id: int
    title: str
    paragraphs: list[Paragraph]
    questions: list[QuestionOut]
    metrics: Metrics
    targets: TextTargets
    attempts: int
    model: str
    cost_usd: float | None = None
    kanji_trainer_error: str | None = None


# --- Reading sessions (issue #9) ---------------------------------------------

SessionStatus = Literal["reading", "questions", "finished"]
#: Only `reading_peek` is ever sent through `POST /api/sessions/{id}/helps`
#: -- `word_lookup` is logged by `POST .../lookups` itself, and
#: `explain`/`translate`/`grammar` (issue #10) by `POST .../assist`
#: (`AssistRequest` below), never this one. A later `tutor` (#11) is
#: expected to get its own endpoint the same way. The `help_events.kind`
#: column is a plain string specifically so none of this needs a schema
#: change later (see `db.py`'s `HelpEvent`).
HelpKind = Literal["reading_peek"]


class SessionCreateRequest(BaseModel):
    text_id: int


class SessionAnswerOut(BaseModel):
    """One question's answer so far, as `GET /api/sessions/{id}` exposes it.

    Both fields are `None` for a question not yet answered; `correct_index`
    is populated only once `option_index` is -- the answer is never revealed
    ahead of actually answering (brief, same spirit as `QuestionOut` leaving
    `answer_index` out entirely).
    """

    option_index: int | None = None
    correct_index: int | None = None


class SessionOut(BaseModel):
    id: int
    text: TextOut
    status: SessionStatus
    started_at: datetime
    active_ms: int
    paused_ms: int
    answers: list[SessionAnswerOut]
    #: Questions answered correctly, set once the last one is answered.
    comprehension_correct: int | None = None


class SessionTimeRequest(BaseModel):
    """`PUT /api/sessions/{id}/time`'s body -- the heartbeat's own running
    totals, applied monotonically (never lowers the stored value, see
    `api/sessions.py`)."""

    active_ms: int
    paused_ms: int


class SessionTimeOut(BaseModel):
    active_ms: int
    paused_ms: int


class HelpRequest(BaseModel):
    kind: HelpKind
    token_id: str


class HelpResult(BaseModel):
    """`counted=False` for a repeat of the same word/session -- a no-op,
    not an error (brief: "a repeat is a no-op that returns `counted:
    false`")."""

    counted: bool
    weight: int


class LookupRequest(BaseModel):
    token_id: str


class WordLookupOut(BaseModel):
    """`POST /api/sessions/{id}/lookups`'s response -- the word popover's
    content once a lookup actually ran (as opposed to the client-side peek,
    which never calls the backend for anything beyond `/helps`)."""

    surface: str
    lemma: str
    #: The lemma's own reading (`Token.lemma_reading`), never the surface's.
    reading: str
    jlpt: int | None = None
    meanings: list[str] = Field(default_factory=list)
    #: e.g. "Kanji Trainer: Guru II", "Not in Kanji Trainer", or "Kanji
    #: Trainer unavailable" -- never raises on its own (brief).
    known_status: str


#: The word popover's three LLM action buttons (issue #10). "Ask tutor"
#: (#11) stays a separate, later endpoint -- not a fourth value here.
AssistKind = Literal["explain", "translate", "grammar"]


class AssistRequest(BaseModel):
    """`POST /api/sessions/{id}/assist`'s body. `explain` acts on the word
    itself (`token_id` must be `is_word`, 422 otherwise); `translate`/
    `grammar` act on the sentence containing it."""

    kind: AssistKind
    token_id: str


class AssistResult(BaseModel):
    """`cached=True` when the answer came from `help_answers` without an
    OpenAI call this time (by this session or an earlier one, for this
    exact text/kind/target); `counted`/`weight` follow `HelpResult`'s own
    convention -- a repeated ask of the same target in the same session is
    `counted: false`, regardless of `cached`."""

    kind: AssistKind
    answer: str
    cached: bool
    counted: bool
    weight: int


class AnswerRequest(BaseModel):
    question_index: int
    option_index: int


class AnswerResult(BaseModel):
    correct: bool
    correct_index: int


class FinishReadingRequest(BaseModel):
    active_ms: int
    paused_ms: int


class LookedUpWordOut(BaseModel):
    word: str
    reading: str
    meaning: str


class SessionSummaryOut(BaseModel):
    chars_per_minute: int
    words_per_minute: int
    helps_per_100_words: float
    questions_correct: int
    questions_total: int
    active_ms: int
    #: In lookup order (first lookup first) -- never alphabetical or by
    #: position in the text.
    looked_up_words: list[LookedUpWordOut] = Field(default_factory=list)
    #: Sum of `HelpEvent.cost_usd` over this session's own assist helps
    #: (issue #10) *and* tutor-chat answers (issue #11) -- 0.0 for a cache
    #: hit (assists only; the chat never caches), the real cost only for an
    #: answer this session's own request actually generated. Never `None`:
    #: an unpriced model's assist still adds 0 here (see `HelpEvent.
    #: cost_usd`'s docstring), it just never shows a per-answer cost of its
    #: own.
    assists_cost_usd: float = 0.0
    #: Number of tutor-chat questions asked this session (issue #11) -- one
    #: `help_events` row per question, `kind: "tutor"`, always counted.
    chat_questions: int = 0


# --- Tutor chat (issue #11) --------------------------------------------------

ChatRole = Literal["user", "assistant"]


class ChatMessageOut(BaseModel):
    """One turn, as `GET /api/sessions/{id}/chat` (reload) and
    `POST .../chat` (the two new turns) both expose it. `focus_sentence_key`/
    `model`/`cost_usd` are `None` save where `db.ChatMessage`'s own docstring
    says they are set (a focused user message; an assistant message)."""

    id: int
    role: ChatRole
    content: str
    focus_sentence_key: str | None = None
    model: str | None = None
    cost_usd: float | None = None
    created_at: datetime


class ChatRequest(BaseModel):
    """`POST /api/sessions/{id}/chat`'s body. `focus_token_id` is the tapped
    word whose *sentence* becomes "About this sentence: ..." in the prompt
    sent for this one question (`help_prompts.build_tutor_messages`) --
    unset for a question asked from the session bar's own chat action,
    which carries no focus at all."""

    content: str
    focus_token_id: str | None = None

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be empty.")
        if len(stripped) > 1000:
            raise ValueError("content must be at most 1000 characters.")
        return stripped


class ChatResult(BaseModel):
    """`counted`/`weight` follow `HelpResult`'s own convention, but every
    question is counted (brief: "a conversation is not a cacheable
    question") -- `help_events.target` is `"chat:<user message id>"`, always
    unique, so the per-session dedupe never actually fires for `kind:
    "tutor"`."""

    user_message: ChatMessageOut
    assistant_message: ChatMessageOut
    counted: bool
    weight: int


class ReadingPaceOut(BaseModel):
    """`GET /api/reading/pace`'s response -- the setup screen's duration
    estimate and the gate's own estimate are both built from this."""

    chars_per_minute: int
    source: Literal["default", "history"]
    #: How many finished sessions the median was actually computed from
    #: (0 when `source == "default"`).
    sessions: int
