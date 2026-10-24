#include "events.hpp"
#include "wintoast/wintoastlib.h"
using namespace WinToastLib;
namespace {
std::wstring appId, appName, iconPath;
std::deque<INT64> retained;
std::wstring wide(const char *value) {
  if (!value || !*value) return {};
  const int size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value, -1, nullptr, 0);
  if (size < 2) return {};
  std::wstring out(size, 0);
  MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value, -1, out.data(), size);
  out.resize(size - 1); return out;
}
class Handler : public IWinToastHandler {
  const std::string id;
public:
  explicit Handler(std::string value) : id(std::move(value)) {}
  void toastActivated() const override { notifyEvent("clicked", id); }
  void toastActivated(int) const override { toastActivated(); }
  void toastActivated(std::wstring) const override { toastActivated(); }
  void toastDismissed(WinToastDismissalReason reason) const override {
    if (reason == UserCanceled) notifyEvent("dismissed", id);
  }
  void toastFailed() const override { notifyEvent("failed", id); }
};
}
int umeko_notify_init(const char *id, const char *name, const char *icon) {
  appId = wide(id); appName = wide(name); iconPath = wide(icon);
  return WinToast::isCompatible() && !appId.empty();
}
int umeko_notify_show(const char *id, const char *title, const char *body) {
  auto center = WinToast::instance();
  if (!center->isInitialized()) {
    center->setAppName(appName); center->setAppUserModelId(appId);
    center->setShortcutPolicy(WinToast::SHORTCUT_POLICY_REQUIRE_CREATE);
    if (!center->initialize()) return 0;
  }
  WinToastTemplate content(iconPath.empty() ? WinToastTemplate::Text02 : WinToastTemplate::ImageAndText02);
  content.setFirstLine(wide(title)); content.setSecondLine(wide(body));
  if (!iconPath.empty()) content.setImagePath(iconPath, WinToastTemplate::CropHint::Circle);
  content.setAudioPath(WinToastTemplate::DefaultSound);
  content.setAudioOption(WinToastTemplate::AudioOption::Default);
  content.setDuration(WinToastTemplate::Duration::System);
  content.setExpiration(24LL * 60 * 60 * 1000);
  // WinToast owns the handler, including after the banner moves into Notification Center.
  const auto handle = center->showToast(content, new Handler(id));
  if (handle < 0) return -1;
  retained.push_back(handle);
  while (retained.size() > 128) {center->hideToast(retained.front()); retained.pop_front();}
  return 1;
}
