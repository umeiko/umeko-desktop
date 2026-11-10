# Background task notifications

Both editions notify when a prompt finishes while the main window is hidden in the tray or minimized. A prompt that runs for more than three minutes also produces a completion banner while the window is visible; shorter foreground prompts finish quietly. Notifications are sent for finished prompts only: cancelling, quitting, reloading and individual tool completions stay quiet, and duplicate completion events produce a single notification. A failed run uses a “needs attention” heading.

The three-minute threshold measures the whole prompt, including startup, thinking, tools and network retries. Each conversation keeps its own start time, so switching chats leaves the timer running. The timer uses a monotonic clock read at start and finish, so system clock changes have no effect. The next prompt starts a fresh timer.

Each notification opens its own conversation. Clicking it restores the window and opens that conversation, which then counts as read. Dismissing a system notification leaves the conversation unread. The text shows the conversation title and an instruction to open it; response content and account keys stay out of notifications. Up to 128 recent notification targets are kept in memory.

- Windows 11: native Windows toast notifications via the pinned WinToast adapter, a stable AppUserModelID and a per-user Start Menu shortcut. Native default sound; entries stay actionable in Notification Center while the process is running (up to 24 hours). Notification permissions, Do Not Disturb, duration and sound follow Windows settings. Python source launches may use the Qt tray fallback; packaged applications load the native adapter.
- macOS: UserNotifications framework, stable application bundle ID, banner/list and native default sound. The first notification asks for alert/sound permission, and the system setting decides from then on. Clicking opens the matching conversation; the system handles grouping, swipe dismissal and Focus. The packaged app uses its normal app icon.
- Linux: the desktop’s `org.freedesktop.Notifications` service, default activation action, icon and standard completion-sound hint. A dormant service is activated before sending; appearance, history and sound follow the desktop environment. C++ uses Qt D-Bus. Python uses dbus-next on a worker event loop, with explicit wire types and GUI-thread activation dispatch.

Notifications work while Umeko is running, including in the tray during background work. Closing the window keeps background agents running; **Exit** in the tray menu quits the app. Install/update confirmation asks before stopping all agents and handing off to the detached installer.

## Build and verification

`native/notifications/` is shared between editions: Windows uses pinned MIT WinToast sources, macOS Objective-C++ calls UserNotifications, and the C ABI queues clicks/dismissals for the GUI thread. Python packaging builds a small DLL/dylib; C++ links the same adapter statically. Packaged smoke checks require native initialization on Windows/macOS; the permission prompt appears when the first notification is sent.

Linux regression tests cover minimized/hidden gating, independent and out-of-order click targets, errors, cancellation/duplicate suppression, closing, D-Bus sender checking, explicit signatures and dormant service activation. Linux fcitx preedit/commit testing is documented in [linux-ime-fcitx5.md](linux-ime-fcitx5.md).

References: [Windows desktop notifications](https://learn.microsoft.com/en-us/windows/apps/design/shell/tiles-and-notifications/toast-desktop-apps), [Apple notification authorization](https://developer.apple.com/documentation/usernotifications/asking-permission-to-use-notifications), [Freedesktop notification specification](https://specifications.freedesktop.org/notification-spec/latest/).
