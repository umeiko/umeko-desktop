#include "events.hpp"
const char *umeko_notify_poll() {
  static thread_local std::string value;
  std::lock_guard<std::mutex> guard(eventMutex);
  if (events.empty()) return nullptr;
  value = std::move(events.front()); events.pop_front();
  return value.c_str();
}
