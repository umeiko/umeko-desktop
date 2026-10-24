# Background task notifications

Both editions notify when a prompt finishes while the main window is hidden in the tray or minimized. Visible windows do not produce completion banners. Cancelling, quitting, reloading, duplicate completion events and individual tool completions do not generate a completion notification. A failed run uses a “needs attention” heading.

Each notification retains its own conversation target. Clicking it restores the window, opens that conversation and lets the existing visible-conversation behavior mark it read. Dismissing a system notification removes its click target without marking an unseen conversation read. Text includes the conversation title and an instruction to open it, never the model response body or account keys. Keep up to 128 recent notification targets in memory.

- Windows 11: native Windows toast notifications via the pinned WinToast adapter, a stable AppUserModelID and a per-user Start Menu shortcut. Native default sound; entries remain actionable in Notification Center while the process is running (up to 24 hours). Notification permissions, Do Not Disturb, duration and sound follow Windows settings. Python source launches may use the Qt tray fallback; packaged applications must load the native adapter.
- macOS: UserNotifications framework, stable application bundle ID, banner/list and native default sound. Ask for alert/sound permission on the first notification; denial does not bypass system preferences with a second transport. Clicking opens the matching conversation; the system owns grouping, swipe dismissal and Focus behavior. The packaged app uses its normal app icon.
- Linux: the desktop’s `org.freedesktop.Notifications` service, default activation action, icon and standard completion-sound hint. Activate a dormant service before sending; appearance/history/sound depend on the desktop environment. C++ uses Qt D-Bus. Python uses dbus-next on a worker event loop, with explicit wire types and GUI-thread activation dispatch.

These notifications apply while Umeko keeps running in the tray, including during background work. They do not launch a fully exited process. Closing the window retains background agents; **Exit** in the tray menu really exits. Install/update confirmation still asks before stopping all agents and handing off to the detached installer.

## Build and verification

`native/notifications/` is shared between editions: Windows uses pinned MIT WinToast sources, macOS Objective-C++ calls UserNotifications, and the C ABI queues clicks/dismissals for the GUI thread. Python packaging builds a small DLL/dylib; C++ links the same adapter statically. Packaged smoke checks require native initialization on Windows/macOS; no permission prompt is shown until a notification is sent.

Linux regression coverage includes minimized/hidden gating, independent and out-of-order click targets, errors, cancellation/duplicate suppression, closing, D-Bus sender checking, explicit signatures and dormant service activation. A real Linux desktop notification was accepted by the local notification daemon. Linux fcitx preedit/commit testing is documented separately in [linux-ime-fcitx5.md](linux-ime-fcitx5.md).

Windows/macOS native compilation and interactive notification-center behavior still require their platform CI and desktop acceptance; Linux verification does not substitute for those checks. Do not dispatch publication workflows until user acceptance.

References: [Windows desktop notifications](https://learn.microsoft.com/en-us/windows/apps/design/shell/tiles-and-notifications/toast-desktop-apps), [Apple notification authorization](https://developer.apple.com/documentation/usernotifications/asking-permission-to-use-notifications), [Freedesktop notification specification](https://specifications.freedesktop.org/notification-spec/latest/).
