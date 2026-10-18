"""Splitting a paragraph's tokens into sentences (issue #10).

"Translate sentence" and "Explain grammar" (the word popover's other two
actions, see `help_prompts.py` and `api/sessions.py`'s assist endpoint) act
on the sentence containing the tapped word, not the word itself -- this
module is the one place that decides where a sentence ends.

A sentence key has the same shape as `Token.id` (`analysis.py`'s
`"<paragraph_index>-<token_index>"`): `"<paragraph_index>-<sentence_index>"`,
so both ride the same `"<paragraph>-<n>"` convention without colliding (a
token id and a sentence key are never compared to each other, only each
used as its own cache/dedupe key).

Pure and independent of the full `Token` shape -- callers pass each token's
`id` and `surface` as a plain `(id, surface)` pair, whether the token came
from the Pydantic `Token` model or the plain dict a `GeneratedText.analysis`
row stores (`api/sessions.py`'s `_find_token` already works with the
latter, and this module never needs more than those two fields).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

#: A sentence ends right after one of these -- the Unicode (full-width)
#: marks a generated text actually uses, plus their ASCII equivalents so a
#: one-off learner-typed paragraph does not misbehave either.
_SENTENCE_ENDERS = "。！？!?"
#: A closing bracket/quote directly following an ender stays part of the
#: sentence it closes -- 「そうだ。」は一つの文 is one sentence, not two.
_CLOSING_BRACKETS = "」』）"


def _is_only(surface: str, chars: str) -> bool:
    return bool(surface) and all(char in chars for char in surface)


@dataclass(frozen=True)
class Sentence:
    """One sentence: its key, its text (the joined surfaces of its
    tokens, in order), and the ids of the tokens it is made of."""

    key: str
    text: str
    token_ids: list[str] = field(default_factory=list)


def split_sentences(
    paragraph_index: int, tokens: Sequence[tuple[str, str]]
) -> list[Sentence]:
    """One `Sentence` per run of tokens ending in a sentence-ender (plus any
    closing bracket/quote directly following it).

    `tokens` is `(token_id, surface)` pairs, in the paragraph's own order. A
    paragraph with no final ender still ends in one (trailing, partial)
    sentence -- every token belongs to exactly one sentence, never dropped.
    """
    sentences: list[Sentence] = []
    current_ids: list[str] = []
    current_text: list[str] = []
    sentence_index = 0

    def flush() -> None:
        nonlocal current_ids, current_text, sentence_index
        if not current_ids:
            return
        sentences.append(
            Sentence(
                key=f"{paragraph_index}-{sentence_index}",
                text="".join(current_text),
                token_ids=current_ids,
            )
        )
        sentence_index += 1
        current_ids = []
        current_text = []

    index = 0
    total = len(tokens)
    while index < total:
        token_id, surface = tokens[index]
        current_ids.append(token_id)
        current_text.append(surface)
        ended = _is_only(surface, _SENTENCE_ENDERS)
        index += 1
        if ended:
            if index < total and _is_only(tokens[index][1], _CLOSING_BRACKETS):
                current_ids.append(tokens[index][0])
                current_text.append(tokens[index][1])
                index += 1
            flush()

    flush()  # the trailing, partial sentence, if the paragraph has one
    return sentences


def find_sentence(
    paragraph_index: int, tokens: Sequence[tuple[str, str]], token_id: str
) -> Sentence | None:
    """The `Sentence` containing `token_id`, or `None` if it is not among
    `tokens` at all."""
    for sentence in split_sentences(paragraph_index, tokens):
        if token_id in sentence.token_ids:
            return sentence
    return None


# --- Partial-sentence selection (issue #32) ---------------------------------


@dataclass(frozen=True)
class Span:
    """A validated word span within one sentence: its two endpoints, the
    `Sentence` containing both, and the span's own text -- the joined
    surfaces of every token from `start_token_id` to `end_token_id`,
    inclusive. A plain (non-word) token caught strictly between the two
    endpoints still contributes its surface here, even though it can never
    be an endpoint itself -- same rule `sumi-reading-text`'s own
    `rangeSelected` (sumi-ui) resolves a drag by."""

    sentence: Sentence
    start_token_id: str
    end_token_id: str
    text: str


def resolve_span(
    paragraph_index: int,
    tokens: Sequence[tuple[str, str, bool]],
    start_token_id: str,
    end_token_id: str,
) -> Span | None:
    """Resolves a `(start_token_id, end_token_id)` pair to a `Span`, or
    `None` if it does not qualify -- shared by `POST .../assist`'s
    `translate_part`/`grammar_part` and the tutor chat's own span focus
    (`api/sessions.py`), so both validate (and dedupe/target) a span by
    exactly the same rule:

    - both ids must resolve to a token in `tokens` (a plain `(id, surface,
      is_word)` triple, the paragraph's own tokens in order -- either
      `Token` or the plain dict a `GeneratedText.analysis` row stores both
      work, since only those three fields are read);
    - both must be in the *same* sentence (`split_sentences`);
    - the start must not come after the end (sentence order, i.e. the
      paragraph's own token order);
    - the inclusive span must contain at least two *word* (`is_word`)
      tokens -- a plain token in between still rides along in `text`, but
      does not count towards this minimum.
    """
    sentences = split_sentences(paragraph_index, [(t[0], t[1]) for t in tokens])
    start_sentence = next((s for s in sentences if start_token_id in s.token_ids), None)
    end_sentence = next((s for s in sentences if end_token_id in s.token_ids), None)
    if start_sentence is None or end_sentence is None or start_sentence.key != end_sentence.key:
        return None

    sentence = start_sentence
    start_index = sentence.token_ids.index(start_token_id)
    end_index = sentence.token_ids.index(end_token_id)
    if start_index > end_index:
        return None

    span_ids = set(sentence.token_ids[start_index : end_index + 1])
    span_tokens = [t for t in tokens if t[0] in span_ids]
    word_count = sum(1 for t in span_tokens if t[2])
    if word_count < 2:
        return None

    return Span(
        sentence=sentence,
        start_token_id=start_token_id,
        end_token_id=end_token_id,
        text="".join(t[1] for t in span_tokens),
    )


#: `span_target`'s own shape, parsed back apart by `parse_span_target` --
#: every id here is `"<paragraph index>-<n>"` (`Token.id`/`Sentence.key`'s
#: own convention, `analysis.py`), with no hyphen of its own, so splitting
#: on `:` and then on `-` is unambiguous.
_SPAN_TARGET_RE = re.compile(r"^(\d+-\d+):(\d+-\d+)-(\d+-\d+)$")


def span_target(sentence_key: str, start_token_id: str, end_token_id: str) -> str:
    """The dedupe/cache target for a span help (issue #32): `"<sentence
    key>:<start token id>-<end token id>"` -- `HelpEvent`/`HelpAnswer`'s
    own `target` for `translate_part`/`grammar_part` (`api/sessions.py`'s
    `assist`). Also reused, unparsed, as the tutor chat's own
    `ChatMessage.focus_sentence_key` for a span-focused question -- no
    schema change needed, the same way `help_events.kind` stays a plain
    string to admit a new kind (see that column's own docstring);
    `parse_span_target` recovers the three pieces from it."""
    return f"{sentence_key}:{start_token_id}-{end_token_id}"


def parse_span_target(value: str) -> tuple[str, str, str] | None:
    """The reverse of `span_target`: `(sentence_key, start_token_id,
    end_token_id)`, or `None` if `value` is not one (e.g. a plain sentence
    key, as a non-span chat focus stores)."""
    match = _SPAN_TARGET_RE.match(value)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)
