import unittest

from v.voice.streaming import SpeechTextSegmenter


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


if __name__ == "__main__":
    unittest.main()
