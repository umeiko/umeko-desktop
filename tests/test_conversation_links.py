"""Explicit web-link recognition: no Qt, filesystem lookup or network required."""
from dataclasses import fields
import unittest

from app.conversation_links import ConversationLink, recognize_links, web_url


class ConversationLinksTests(unittest.TestCase):
    def test_paths_source_names_and_bare_domains_remain_plain_text(self):
        values = ("a/b", "1/2", "and/or", "src/app.py:12", r"C:\x\y",
                  "~/notes.md", "main.py", "README.md", "example.com", "app.py")
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(recognize_links(value), [])
                self.assertIsNone(web_url(value))
        self.assertEqual(recognize_links(" ".join(values)), [])

    def test_explicit_web_prefixes_queries_and_unicode_offsets(self):
        text = "😀 https://example.com/a?q=1#part http://localhost:8123 www.example.org"
        links = recognize_links(text)
        self.assertEqual([link.target for link in links], [
            "https://example.com/a?q=1#part", "http://localhost:8123", "https://www.example.org"])
        self.assertEqual([link.kind for link in links], ["url"] * 3)
        self.assertEqual(links[0].start, 2)
        self.assertEqual([text[link.start:link.end] for link in links], [
            "https://example.com/a?q=1#part", "http://localhost:8123", "www.example.org"])

    def test_link_record_has_only_web_span_and_target_fields(self):
        self.assertEqual([field.name for field in fields(ConversationLink)],
                         ["start", "end", "kind", "target"])
        self.assertEqual(recognize_links("www.example.com"), [
            ConversationLink(0, 15, "url", "https://www.example.com")])

    def test_prefixes_are_case_insensitive(self):
        for value, expected in (
                ("HTTP://example.com/a", "HTTP://example.com/a"),
                ("HTTPS://example.com/a", "HTTPS://example.com/a"),
                ("WWW.example.com/a", "https://WWW.example.com/a")):
            with self.subTest(value=value):
                self.assertEqual(web_url(value), expected)
                self.assertEqual([link.target for link in recognize_links(value)], [expected])

    def test_punctuation_preserves_balanced_url_parentheses(self):
        text = "结果：example.com，网址（www.example.org）。另见 https://example.com/a_(b)."
        self.assertEqual([text[link.start:link.end] for link in recognize_links(text)], [
            "www.example.org", "https://example.com/a_(b)"])

    def test_syntactically_valid_hosts_do_not_require_public_suffix_lookup(self):
        for value in ("http://localhost:8123", "http://127.0.0.1:3000/x",
                      "https://[::1]:3000", "https://example.invalid/guide",
                      "https://例子.中国", "www.example.invalid/guide"):
            with self.subTest(value=value):
                expected = "https://" + value if value.startswith("www.") else value
                self.assertEqual(web_url(value), expected)

    def test_unsafe_targets_and_malformed_urls_are_rejected(self):
        for value in ("file:///tmp/readme", "javascript:alert(1)", "ftp://example.com",
                      "data:text/plain,example.com", "example.com:8443/path", "例子.中国",
                      "https://example.com:99999", "https://user:password@example.com",
                      "https://bad_host.com", "https://-bad.com", "https://", "www.",
                      " https://example.com", "https://example.com with space"):
            with self.subTest(value=value):
                self.assertIsNone(web_url(value))

    def test_no_inner_link_from_non_web_tokens(self):
        text = (r"name@example.com not_example.com /missing/example.com C:\missing\example.com "
                "file:///example.com javascript:example.com custom:example.com")
        self.assertEqual(recognize_links(text), [])

    def test_fenced_code_and_unfinished_fences_are_not_linked(self):
        text = ("https://example.com\n```python\nhttps://example.org\n```\n"
                "www.example.net\n~~~\nhttp://example.edu")
        self.assertEqual([text[link.start:link.end] for link in recognize_links(text)], [
            "https://example.com", "www.example.net"])

    def test_cancelled_scan_returns_no_links(self):
        self.assertEqual(recognize_links("https://example.com " * 200,
                                         cancelled=lambda: True), [])


if __name__ == "__main__":
    unittest.main()
