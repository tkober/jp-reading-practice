"""Prompts for the three LLM helps (issue #10): Explain word, Translate
sentence, Explain grammar -- the word popover's action buttons.

Same fixed-frame spirit as `prompts.py`'s generation frame: `_ROLE` is one
role description shared by all three, and each builder always gives the
model the *whole* text as context, plus the specific target (a word or the
sentence containing it) the learner tapped on -- never just the target in
isolation, since "this sentence"/"in this sentence" phrasing in the
question only makes sense with the surrounding text in view, and a
generated text is short enough that sending it whole costs nothing worth
trimming for.

Each answer is capped in words (not enforced in code -- the model is simply
asked to keep to it, same spirit as the length target in `prompts.py`'s
own generation frame) and is plain English text: no markdown, no romaji,
Japanese quoted exactly as written. Snapshot-ish tests on the frames live
in `tests/test_help_prompts.py`.
"""

from __future__ import annotations

_ROLE = """You are a patient, encouraging Japanese tutor for an English-speaking
learner who is reading a short text in Japanese. You are helping them with
one specific question about that text, calibrated to the text's own level
-- do not introduce vocabulary or grammar harder than what the text itself
uses, and do not drift into teaching anything beyond what was asked.

Answer in plain English prose, no markdown formatting (no headings, no
bullet points, no bold/italic markup -- line breaks between sentences are
fine). Never use romaji. Quote Japanese exactly as written, in its own
script, never transliterated."""


def _context_block(text: str) -> str:
    return f"""# The text
{text.strip()}"""


def build_explain_word_instructions(*, text: str, surface: str, sentence: str) -> str:
    """"Explain word": meaning in context, dictionary form + what the
    inflection does, a nuance/collocation note if relevant -- at most 80
    words."""
    return f"""{_ROLE}

{_context_block(text)}

# The question
Explain the word "{surface.strip()}" as it is used in this sentence from the
text above:
{sentence.strip()}

Cover, briefly:
- What it means *in this sentence* -- not just a generic dictionary gloss.
- Its dictionary (base) form, if the word as written is inflected or
  conjugated, and what that inflection is doing here.
- A short nuance or common-collocation note, only if it is actually useful
  for understanding this occurrence -- leave it out if there is nothing
  worth adding.

At most 80 words."""


def build_translate_sentence_instructions(*, text: str, sentence: str) -> str:
    """"Translate sentence": a natural English translation, then one short
    line on anything a learner would likely misread -- at most 60 words."""
    return f"""{_ROLE}

{_context_block(text)}

# The question
Translate this sentence from the text above into natural English:
{sentence.strip()}

First give the translation on its own. Then, on a new line, one short note
on anything in the sentence a learner at this level would likely misread or
misparse -- or nothing at all if there is no real risk of that.

At most 60 words in total."""


def build_explain_grammar_instructions(*, text: str, sentence: str) -> str:
    """"Explain grammar": the 1-3 grammar points that actually carry the
    sentence's meaning -- at most 120 words."""
    return f"""{_ROLE}

{_context_block(text)}

# The question
Explain the grammar of this sentence from the text above:
{sentence.strip()}

Name the 1 to 3 grammar points that actually carry this sentence's meaning
(for example a particle's role, a verb form, a conditional or causative
pattern) -- not a word-by-word breakdown of everything in it. For each one,
name the pattern and say briefly what it is doing *here*, in this sentence.

At most 120 words."""
