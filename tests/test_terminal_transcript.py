import unittest

from prompt_toolkit.layout.controls import FormattedTextControl, UIContent

from app.terminal_transcript import CHUNK_CHARS, TranscriptFeed
from app.terminal_viewport import TranscriptWindow


class TerminalTranscriptTests(unittest.TestCase):
    def test_full_message_and_thinking_arrive_without_resending_the_prefix(self):
        feed = TranscriptFeed()
        body = "字" * (CHUNK_CHARS + 17)
        initial = {"role": "assistant", "text": body, "thinking": "Provider reasoning"}
        feed.latest = [initial]
        frames = list(iter(feed.next_frame, None))
        self.assertEqual(frames[0]["keep"], 0)
        self.assertEqual("".join(item["append"] for item in frames if item.get("field") == "text"), body)
        self.assertEqual("".join(item["append"] for item in frames if item.get("field") == "thinking"),
                         "Provider reasoning")
        feed.latest = [{**initial, "text": body + " tail"}]
        self.assertEqual(list(iter(feed.next_frame, None)), [
            {"event": "transcript", "field": "text", "append": " tail"},
            {"event": "transcript", "complete": True},
        ])

    def test_wrap_scroll_follows_updates_until_user_pages_up(self):
        viewport = TranscriptWindow(FormattedTextControl())

        def update(line_count):
            content = UIContent(get_line=lambda index: [("", "x" * 32)], line_count=line_count)
            viewport._scroll(content, 8, 3)

        update(2)
        self.assertEqual((viewport.vertical_scroll, viewport.vertical_scroll_2), (1, 1))
        viewport.scroll_page(-1)
        update(3)
        self.assertEqual((viewport.vertical_scroll, viewport.vertical_scroll_2), (0, 3))
        viewport.scroll_page(1)
        viewport.scroll_page(1)
        viewport.scroll_page(1)
        update(3)
        self.assertIsNone(viewport.anchor)
        self.assertEqual((viewport.vertical_scroll, viewport.vertical_scroll_2), (2, 1))

    def test_wide_characters_wrap_at_cell_boundaries(self):
        viewport = TranscriptWindow(FormattedTextControl())
        content = UIContent(get_line=lambda _: [("", "字" * 20)], line_count=1)
        viewport._scroll(content, 5, 3)
        self.assertEqual((viewport.vertical_scroll, viewport.vertical_scroll_2), (0, 7))


if __name__ == "__main__":
    unittest.main()
