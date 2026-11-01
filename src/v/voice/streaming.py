"""Incremental sentence and clause segmentation for low-latency speech output."""

from __future__ import annotations

import re


def clean_speech_text(text: str) -> str:
    """Remove Markdown presentation syntax before sending text to TTS."""
    if not isinstance(text, str):
        raise TypeError("Speech text must be a string.")

    cleaned = text
    cleaned = re.sub(r"(?ms)^[ \t]*```[^\n]*\n.*?^[ \t]*```[ \t]*$", " ", cleaned)
    cleaned = re.sub(r"(?ms)^[ \t]*~~~[^\n]*\n.*?^[ \t]*~~~[ \t]*$", " ", cleaned)
    cleaned = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", lambda match: match.group(1), cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s{0,3}>\s?", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*(?:[-+*]|\d+[.)])\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$", " ", cleaned)
    cleaned = re.sub(
        r"(?<!\\w)(?:\\*{1,3}|_{1,3}|~~)(?=\\S)|"
        r"(?<=\\S)(?:\\*{1,3}|_{1,3}|~~)(?!\\w)",
        "",
        cleaned,
    )
    cleaned = cleaned.replace("`", "")
    cleaned = cleaned.replace("|", " ")
    cleaned = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>])", r"\1", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()

class SpeechTextSegmenter:
    """Release complete, natural-sounding text segments as streamed tokens arrive."""

    _SENTENCE_BOUNDARY = re.compile(r"""[.!?]+["'”’)\]}*_~\x60]*(?=\s)""")
    _CLAUSE_BOUNDARY = re.compile(r"""[,;:]["'”’)\]}*_~\x60]*(?=\s)""")
    _WORD = re.compile(r"\b[\w’'-]+\b")
    _ABBREVIATIONS = frozenset(
        {
            "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.",
            "vs.", "etc.", "e.g.", "i.e.", "a.m.", "p.m.", "no.", "fig.",
        }
    )
    _CLOSING = " \t\r\n\"'”’)]}*_~\x60"

    def __init__(self, *, minimum_clause_words: int = 8) -> None:
        if isinstance(minimum_clause_words, bool) or not isinstance(
            minimum_clause_words, int
        ):
            raise ValueError("Minimum clause words must be a whole number.")
        if minimum_clause_words < 3:
            raise ValueError("Minimum clause words must be at least 3.")
        self.minimum_clause_words = minimum_clause_words
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        """Add streamed text and return every complete segment found."""
        if not isinstance(text, str):
            raise TypeError("Speech text chunks must be strings.")
        self._buffer += text
        return self._extract(final=False)

    def flush(self) -> list[str]:
        """Return any final unterminated text when generation ends."""
        return self._extract(final=True)

    def _is_abbreviation(self, candidate: str) -> bool:
        cleaned = candidate.rstrip(self._CLOSING).strip()
        if not cleaned:
            return False
        token = cleaned.split()[-1].casefold()
        if token in self._ABBREVIATIONS:
            return True
        return re.fullmatch(r"(?:[a-z]\.){2,}", token) is not None

    def _find_boundary(self) -> re.Match[str] | None:
        for match in self._SENTENCE_BOUNDARY.finditer(self._buffer):
            candidate = self._buffer[: match.end()]
            if not self._is_abbreviation(candidate):
                return match

        for match in self._CLAUSE_BOUNDARY.finditer(self._buffer):
            candidate = self._buffer[: match.end()]
            word_count = len(self._WORD.findall(candidate))
            threshold = (
                self.minimum_clause_words
                if match.group(0).startswith(",")
                else max(6, self.minimum_clause_words - 3)
            )
            if word_count >= threshold:
                return match
        return None

    def _extract(self, *, final: bool) -> list[str]:
        segments: list[str] = []
        while self._buffer:
            boundary = self._find_boundary()
            if boundary is None:
                break
            segment = self._buffer[: boundary.end()].strip()
            self._buffer = self._buffer[boundary.end() :].lstrip()
            if segment:
                segments.append(segment)

        if final and self._buffer.strip():
            segments.append(self._buffer.strip())
            self._buffer = ""
        return segments
