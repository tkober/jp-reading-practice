"""Prompts for the LLM helps: Explain word, Translate sentence, Explain
grammar (the word popover's action buttons, issue #10) and the tutor chat
(issue #11).

Same fixed-frame spirit as `prompts.py`'s generation frame: `_ROLE` is one
role description shared by all of them, and every builder always gives the
model the *whole* text as context, plus the specific target (a word, the
sentence containing it, or -- for the chat -- the conversation so far) the
learner is asking about -- never just the target in isolation, since "this
sentence"/"in this sentence" phrasing in the question only makes sense with
the surrounding text in view, and a generated text is short enough that
sending it whole costs nothing worth trimming for.

Each answer is capped in words (not enforced in code -- the model is simply
asked to keep to it, same spirit as the length target in `prompts.py`'s
own generation frame) and is plain English text: no markdown, no romaji,
Japanese quoted exactly as written. Snapshot-ish tests on the frames live
in `tests/test_help_prompts.py`.
"""

from __future__ import annotations

from collections.abc import Sequence

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


# --- Tutor chat (issue #11) --------------------------------------------------

_TUTOR_RULES = """You are chatting with the learner about the text above, one question at a
time. Answer in plain English, as short as you can while still answering the
question -- at most 120 words, unless the learner explicitly asks for more.

Never translate the whole text in one go, even if asked directly for a full
translation -- offer to go through it sentence by sentence instead, and give
the first sentence's translation right away as the start of that.

Only answer questions about this text, its words, or its grammar. If asked
something unrelated to it, reply with one short sentence steering the
conversation back to the text, and nothing else."""


def build_tutor_system_prompt(*, text: str) -> str:
    """The chat's system message: the shared tutor role, the whole text, and
    the chat-specific rules above (short answers, no one-shot translation,
    redirect anything unrelated) -- sent once per call, same as the other
    three helps' own frame, since a chat completion has no server-side
    notion of "the system message I sent last time"."""
    return f"""{_ROLE}

{_context_block(text)}

# Chat rules
{_TUTOR_RULES}"""


def build_tutor_messages(
    *,
    text: str,
    history: Sequence[tuple[str, str]],
    question: str,
    focus_sentence: str | None = None,
) -> list[dict[str, str]]:
    """The full `messages` array for one tutor-chat call: the system frame
    above, then every prior turn of this session's conversation (oldest
    first, exactly as stored -- a past turn never gets its own focus prefix
    re-added here, only the *new* question below does), then the new
    question itself, prefixed with the focus sentence when there is one
    ("About this sentence: ...").

    `history` is `(role, content)` pairs, already in the order they were
    asked -- `api/sessions.py`'s `post_chat` reads them straight from
    `db.ChatMessage` before the new question is appended.
    """
    messages = [{"role": "system", "content": build_tutor_system_prompt(text=text)}]
    for role, content in history:
        messages.append({"role": role, "content": content})

    final_question = question.strip()
    if focus_sentence:
        final_question = f"About this sentence: {focus_sentence.strip()}\n\n{final_question}"
    messages.append({"role": "user", "content": final_question})
    return messages
