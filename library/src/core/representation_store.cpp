#include "representation_store.hpp"
#include <list>
#include <mutex>
#include <unordered_map>
namespace graphmine::representation_store {
namespace {
struct Cache {
  std::mutex mutex;
  std::list<std::string> recent;
  std::unordered_map<std::string, Entry> entries;
  std::size_t limit = 128 * 1024 * 1024, bytes = 0;
  std::uint64_t hits = 0, misses = 0, evictions = 0;
  void evict() {
    const auto found = entries.find(recent.back());
    bytes -= found->second.bytes;
    entries.erase(found);
    recent.pop_back();
    ++evictions;
  }
};
Cache& cache() {
  static Cache instance;
  return instance;
}

}  // namespace
std::optional<Entry> lookup(const std::string& key) {
  auto& state = cache();
  std::lock_guard<std::mutex> lock(state.mutex);
  const auto found = state.entries.find(key);
  if (found == state.entries.end()) {
    ++state.misses;
    return {};
  }
  ++state.hits;
  state.recent.splice(state.recent.begin(), state.recent, found->second.position);
  return found->second;
}
bool insert(const std::string& key, std::shared_ptr<const void> value, std::size_t bytes,
            std::uint64_t work, std::shared_ptr<const void>* winner) {
  auto& state = cache();
  std::lock_guard<std::mutex> lock(state.mutex);
  if (bytes > state.limit || !state.limit) return false;
  if (const auto found = state.entries.find(key); found != state.entries.end()) {
    if (winner) *winner = found->second.value;
    return true;
  }
  while (state.bytes > state.limit - bytes) state.evict();
  state.recent.push_front(key);
  if (winner) *winner = value;
  state.entries.emplace(key, Entry{std::move(value), bytes, work, state.recent.begin()});
  state.bytes += bytes;
  return true;
}
Stats control(std::optional<std::size_t> limit, bool clear) {
  auto& state = cache();
  std::lock_guard<std::mutex> lock(state.mutex);
  if (limit) {
    state.limit = *limit;
    while (state.bytes > state.limit) state.evict();
  }
  if (clear) {
    state.entries.clear();
    state.recent.clear();
    state.bytes = 0;
    state.hits = state.misses = state.evictions = 0;
  }
  return {state.limit, state.bytes, state.entries.size(), state.hits, state.misses, state.evictions};
}
}  // namespace graphmine::representation_store
