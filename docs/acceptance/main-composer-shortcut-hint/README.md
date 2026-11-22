# Main desktop composer shortcut hint (#195)

Only the main desktop Composer footer changed. The idle/running keyboard text and its row space were removed. The send/stop button, its action tooltip and accessibility label, and loading/compacting and task lifecycle status remain. The shared keyboard and input method handlers are unchanged.

| Actual Linux Qt offscreen layout | Before | After |
| --- | --- | --- |
| 1450 px window | [Before](before-wide.png) | [After](after-wide.png) |
| 860 px window | [Before](before-narrow.png) | [After](after-narrow.png) |

The trailing control row went from 222.5 to 33 logical pixels in both cases, equal to the unchanged send button width. Images are cropped from the actual Main window using a new profile and synthetic Chinese draft. The matching Pi 1.5.2 bridge verified; no external model or account was required. This checkout's main UI is Python/PySide6 with Qt Quick; native C++ components are platform helpers, not a separate composer edition.

Run `python tests/composer_shortcut_hint_ui_smoke.py`. Real Qt events verify Enter reaches the submit signal once, Ctrl/Alt/Shift+Enter insert a newline without submitting, and synthetic Chinese preedit/commit preserves the guard. This is not Windows or macOS native IME acceptance.
