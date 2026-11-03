"""Plain-text link recognition: no Qt or runtime network is required."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.conversation_links import (
    ConversationLink, EXECUTABLE_SUFFIXES, is_executable_path,
    recognize_links, web_url,
)


class ConversationLinksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def file(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
        return str(path.resolve())

    def test_relative_absolute_and_line_column(self):
        target = self.file("src/main.py")
        text = f"src/main.py:12:3 and {target}:4"
        links = recognize_links(text, self.root)
        self.assertEqual([(x.kind, x.target, x.line, x.column) for x in links], [
            ("path", target, 12, 3), ("path", target, 4, None)])
        self.assertEqual([text[x.start:x.end] for x in links], ["src/main.py:12:3", f"{target}:4"])

    def test_bare_filename_and_directory(self):
        target = self.file("main.py")
        (self.root / "docs").mkdir()
        links = recognize_links("Open main.py:9 and docs", self.root)
        self.assertEqual([x.target for x in links], [target, str((self.root / "docs").resolve())])
        self.assertEqual(links[0].line, 9)

    def test_spaces_in_quotes_inline_fragment_and_project_component(self):
        first = self.file("my file.txt")
        second = self.file("docs/release notes.md")
        text = 'Read "my file.txt:5" then docs/release notes.md today.'
        self.assertEqual([x.target for x in recognize_links(text, self.root)], [first, second])
        self.assertEqual(recognize_links("my file.txt", self.root)[0].target, first)
        self.assertEqual(recognize_links("`my file.txt`", self.root)[0].target, first)

    def test_chinese_and_balanced_punctuation(self):
        target = self.file("notes.md")
        text = "结果：notes.md:2，网址（example.com）。另见 https://example.com/a_(b)."
        links = recognize_links(text, self.root)
        self.assertEqual([text[x.start:x.end] for x in links], [
            "notes.md:2", "example.com", "https://example.com/a_(b)"])
        self.assertEqual(links[0].target, target)

    def test_windows_paths_on_any_host(self):
        text = r'C:\work\main.py:10:2 C:/work/other.py "C:\Program Files\notes.txt:7"'
        existing = {r"C:\work\main.py", r"C:\work\other.py", r"C:\Program Files\notes.txt"}
        with patch("app.conversation_links.os.path.exists", side_effect=lambda value: value in existing):
            links = recognize_links(text, self.root)
        self.assertEqual([(x.target, x.line, x.column) for x in links], [
            (r"C:\work\main.py", 10, 2), (r"C:\work\other.py", None, None),
            (r"C:\Program Files\notes.txt", 7, None)])

    def test_home_path(self):
        target = self.file("home.md")
        with patch("app.conversation_links.Path.expanduser", autospec=True,
                   side_effect=lambda value: self.root / value.as_posix()[2:] if value.as_posix().startswith("~/") else value):
            links = recognize_links("~/home.md:3", self.root)
        self.assertEqual(links[0].target, target)
        self.assertEqual(links[0].line, 3)

    def test_filesystem_precedes_domain_and_is_rechecked_per_render(self):
        target = self.file("example.com")
        first = recognize_links("example.com", self.root)
        Path(target).unlink()
        second = recognize_links("example.com", self.root)
        self.assertEqual(first, [ConversationLink(0, 11, "path", target)])
        self.assertEqual(second, [ConversationLink(0, 11, "url", "https://example.com")])

    def test_missing_absolute_path_does_not_link_inner_domain(self):
        text = r"/missing/example.com C:\missing\example.com file:///example.com javascript:example.com custom:example.com"
        self.assertEqual(recognize_links(text, self.root), [])

    def test_source_names_and_unknown_suffixes_do_not_link(self):
        text = "main.py README.md script.sh source.rs example.unknownsuffix missing/main.py"
        self.assertEqual(recognize_links(text, self.root), [])

    def test_urls_www_domains_queries_and_unicode_offsets(self):
        text = "😀 https://example.com/a?q=1#part www.example.org example.co.uk"
        links = recognize_links(text, self.root)
        self.assertEqual([x.target for x in links], [
            "https://example.com/a?q=1#part", "https://www.example.org", "https://example.co.uk"])
        self.assertEqual(links[0].start, 2)

    def test_no_substring_link_from_invalid_token(self):
        self.assertEqual(recognize_links("name@example.com not_example.com /missing/example.com", self.root), [])

    def test_fenced_code_and_unfinished_fences_are_not_linked(self):
        self.file("main.py")
        text = "example.com\n```python\nmain.py https://example.org\n```\nwww.example.net\n~~~\nmain.py"
        links = recognize_links(text, self.root)
        self.assertEqual([text[x.start:x.end] for x in links], ["example.com", "www.example.net"])

    def test_explicit_urls_local_web_tools_and_psl(self):
        for value in ("http://localhost:8123", "http://127.0.0.1:3000/x", "https://[::1]:3000"):
            with self.subTest(value=value):
                self.assertEqual(web_url(value), value)
        self.assertEqual(web_url("example.com:8443/path"), "https://example.com:8443/path")
        self.assertEqual(web_url("例子.中国"), "https://例子.中国")
        for value in ("file:///tmp/readme", "javascript:alert(1)", "ftp://example.com",
                      "data:text/plain,example.com", "example.invalid", "co.uk", "README.md",
                      "main.py", "example.com:99999", "https://user:password@example.com",
                      "https://bad_host.com", " example.com", "example.com with space"):
            with self.subTest(value=value):
                self.assertIsNone(web_url(value))

    def test_executable_types_and_extensionless_posix(self):
        for suffix in (".exe", ".bat", ".cmd", ".ps1", ".sh", ".msi", ".com", ".lnk", ".app", ".command", ".py", ".js"):
            self.assertIn(suffix, EXECUTABLE_SUFFIXES)
            self.assertTrue(is_executable_path("tool" + suffix.upper()))
        self.assertFalse(is_executable_path("readme.txt"))
        if os.name != "nt":
            target = Path(self.file("runner"))
            target.chmod(0o700)
            self.assertTrue(is_executable_path(target))
            target.chmod(0o600)
            self.assertFalse(is_executable_path(target))


if __name__ == "__main__":
    unittest.main()
