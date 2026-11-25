"""Scroll a read-only wrapped transcript independently of the composer's cursor."""
from prompt_toolkit.formatted_text.utils import fragment_list_to_text
from prompt_toolkit.layout import Window
from prompt_toolkit.utils import get_cwidth


class TranscriptWindow(Window):
    def __init__(self, content):
        super().__init__(content, wrap_lines=True, always_hide_cursor=True, dont_extend_height=True)
        self.anchor = None
        self._geometry = None
        self._heights = {}

    def _line_height(self, line):
        if line in self._heights:
            return self._heights[line]
        content, width, _ = self._geometry
        text = fragment_list_to_text(content.get_line(line))
        if text.isascii():
            height = max(1, (len(text) + width - 1) // width)
        else:
            height, column = 1, 0
            for character in text:
                cells = get_cwidth(character)
                if column + cells > width:
                    height += 1
                    column = 0
                column += cells
        self._heights[line] = height
        return height

    def _tail(self):
        content, _, height = self._geometry
        remaining = height
        for line in range(content.line_count - 1, -1, -1):
            wrapped = self._line_height(line)
            if wrapped >= remaining:
                return line, wrapped - remaining
            remaining -= wrapped
        return 0, 0

    def _scroll(self, ui_content, width, height):
        self.horizontal_scroll = 0
        if width < 1 or height < 1 or not ui_content.line_count:
            self._geometry = None
            self.vertical_scroll = self.vertical_scroll_2 = 0
            return
        if not self._geometry or self._geometry[:2] != (ui_content, width):
            self._heights.clear()
        self._geometry = (ui_content, width, height)
        tail = self._tail()
        if self.anchor is None:
            position = tail
        else:
            line = min(self.anchor[0], tail[0])
            offset = min(self.anchor[1], self._line_height(line) - 1)
            position = min((line, offset), tail)
            self.anchor = position
        self.vertical_scroll, self.vertical_scroll_2 = position

    def scroll_page(self, direction):
        if self._geometry is None:
            return
        _, _, height = self._geometry
        tail = self._tail()
        line, offset = self.anchor or tail
        remaining = max(1, height - 1)
        while remaining:
            if direction < 0:
                if offset >= remaining:
                    offset -= remaining
                    break
                if line == 0:
                    offset = 0
                    break
                remaining -= offset + 1
                line -= 1
                offset = self._line_height(line) - 1
            else:
                if (line, offset) >= tail:
                    break
                until_next = self._line_height(line) - offset
                if until_next > remaining:
                    offset += remaining
                    break
                line += 1
                offset = 0
                remaining -= until_next
        position = min((line, offset), tail)
        self.anchor = position if position < tail else None
