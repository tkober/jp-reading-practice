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
