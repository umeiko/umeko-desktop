#pragma once
#ifdef _WIN32
#define UMEKO_NOTIFY_EXPORT __declspec(dllexport)
#else
#define UMEKO_NOTIFY_EXPORT __attribute__((visibility("default")))
#endif
extern "C" {
// Called on the application's GUI thread. Callbacks are polled, never run in Qt.
UMEKO_NOTIFY_EXPORT int umeko_notify_init(const char *appId, const char *name, const char *icon);
UMEKO_NOTIFY_EXPORT int umeko_notify_show(const char *id, const char *title, const char *body);
UMEKO_NOTIFY_EXPORT const char *umeko_notify_poll();
}
