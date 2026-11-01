import unittest

from v.voice.streaming import SpeechTextSegmenter, clean_speech_text


class SpeechTextSegmenterTests(unittest.TestCase):
    def test_releases_sentences_incrementally(self):
        segmenter = SpeechTextSegmenter()
        self.assertEqual(segmenter.feed("Hello there."), [])
        self.assertEqual(
            segmenter.feed(" How are you? Next"),
            ["Hello there.", "How are you?"],
        )
        self.assertEqual(segmenter.flush(), ["Next"])

    def test_does_not_split_common_abbreviations_or_decimals(self):
        segmenter = SpeechTextSegmenter()
        self.assertEqual(
            segmenter.feed("Dr. Smith paid 3.14 dollars. Nice."),
            ["Dr. Smith paid 3.14 dollars."],
        )
        self.assertEqual(segmenter.flush(), ["Nice."])

    def test_releases_a_long_clause_before_the_sentence_finishes(self):
        segmenter = SpeechTextSegmenter(minimum_clause_words=8)
        self.assertEqual(
            segmenter.feed(
                "This is a reasonably long opening phrase with enough words, "
                "and the rest follows afterward."
            ),
            ["This is a reasonably long opening phrase with enough words,"],
        )
        self.assertEqual(
            segmenter.flush(),
            ["and the rest follows afterward."],
        )

    def test_releases_markdown_emphasis_wrapped_sentences(self):
        segmenter = SpeechTextSegmenter()
        self.assertEqual(
            segmenter.feed("**The first sentence ends here.** Next one."),
            ["**The first sentence ends here.**"],
        )
        self.assertEqual(
            segmenter.flush(),
            ["Next one."],
        )

    def test_rejects_non_string_chunks(self):
        segmenter = SpeechTextSegmenter()
        with self.assertRaisesRegex(TypeError, "must be strings"):
            segmenter.feed(b"audio")

    def test_cleans_markdown_before_speech(self):
        text = (
            "## Important\n"
            "**This is bold** and *this is italic*. "
            "Use `git pull` and [the documentation](https://example.com).\n\n"
            "```python\nprint('do not read this code')\n```"
        )
        self.assertEqual(
            clean_speech_text(text),
            "Important This is bold and this is italic. "
            "Use git pull and the documentation.",
        )

    def test_removes_markdown_list_markers_without_removing_words(self):
        self.assertEqual(
            clean_speech_text("* First item\n- Second item\n1. Third item"),
            "First item Second item Third item",
        )

    def test_preserves_underscores_inside_identifiers(self):
        self.assertEqual(
            clean_speech_text("The CPU is i7_4770K and path uses snake_case."),
            "The CPU is i7_4770K and path uses snake_case.",
        )

    def test_default_segmenter_releases_shorter_clauses(self):
        segmenter = SpeechTextSegmenter()
        self.assertEqual(
            segmenter.feed("Here are eight useful words before the comma, and more."),
            ["Here are eight useful words before the comma,"],
        )


if __name__ == "__main__":
    unittest.main()
