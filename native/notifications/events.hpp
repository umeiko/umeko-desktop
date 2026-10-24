#pragma once
#include "notify.h"
#include <deque>
#include <mutex>
#include <string>
inline std::mutex eventMutex;
inline std::deque<std::string> events;
inline void notifyEvent(const char *kind, const std::string &id) {
  std::lock_guard<std::mutex> guard(eventMutex);
  if (events.size() < 256) events.emplace_back(std::string(kind) + ":" + id);
}
