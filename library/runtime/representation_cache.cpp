#include "representation_cache.hpp"

#include <list>
#include <mutex>
#include <unordered_map>

#include "catalog_data.hpp"

namespace graphmine::runtime {
namespace {
struct Entry {
  std::shared_ptr<const void> value;
  std::size_t bytes;
  std::uint64_t work;
  std::list<std::string>::iterator position;
};
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
            std::uint64_t work) {
  auto& state = cache();
  std::lock_guard<std::mutex> lock(state.mutex);
  if (bytes > state.limit || !state.limit) return false;
  if (state.entries.count(key)) return true;  // A concurrent equivalent build won.
  while (state.bytes > state.limit - bytes) state.evict();
  state.recent.push_front(key);
  state.entries.emplace(key, Entry{std::move(value), bytes, work, state.recent.begin()});
  state.bytes += bytes;
  return true;
}
void record(Work& work, const char* kind, const std::string& key, bool hit, bool retained) {
  if (work.representations.size() < 32)
    work.representations.push_back(
        json::object{{"kind", kind}, {"key", key}, {"hit", hit}, {"retained", retained}});
}
}  // namespace

std::shared_ptr<const Graph> cached_graph(const json::value& value, Work& work) {
  const auto fingerprint = input_fingerprint(value);
  const auto key = fingerprint + ":canonical-records-v1:" + implementation_sha256;
  if (const auto found = lookup(key)) {
    work.tick(found->work);
    record(work, "canonical_graph", key, true, true);
    return std::static_pointer_cast<const Graph>(found->value);
  }
  work.tick(0);
  auto graph = std::make_shared<const Graph>(parse_graph(value));
  // Conservative accounting covers record containers, property nodes, indices
  // and vector capacity. Active requests retain their own shared ownership.
  const auto bytes = json::serialize(value).size() * 16 +
                     (graph->vertex_count() + graph->edge_count()) * 512 + 1024;
  const bool retained = insert(key, graph, bytes, 0);
  record(work, "canonical_graph", key, false, retained);
  work.tick(0);
  return graph;
}

WeightedGraph cached_weighted_graph(const std::string& semantics, Work& work,
                                    const std::function<WeightedGraph()>& build) {
  const auto key =
      work.input_fingerprint + ":weighted-adjacency-v1:" + semantics + ":" + implementation_sha256;
  if (const auto found = lookup(key)) {
    // Reuse must not make a smaller candidate budget admit a previously
    // inadmissible request. Returned values are copies so callers cannot poison it.
    work.tick(found->work);
    record(work, "weighted_adjacency", key, true, true);
    return *std::static_pointer_cast<const WeightedGraph>(found->value);
  }
  const auto before = work.candidates;
  auto graph = std::make_shared<const WeightedGraph>(build());
  std::size_t bytes = 1024 + graph->rows.capacity() * sizeof(std::vector<Arc>);
  for (const auto& row : graph->rows) bytes += row.capacity() * sizeof(Arc);
  const bool retained = insert(key, graph, bytes, work.candidates - before);
  record(work, "weighted_adjacency", key, false, retained);
  return *graph;
}

json::object representation_cache_request(const json::object& request) {
  fields(request, {"command", "action", "max_bytes"}, {"command"});
  const auto action =
      request.contains("action") ? string(request.at("action"), "action") : "status";
  require(action == "status" || action == "clear" || action == "configure", "Unknown cache action");
  require(action == "configure" || !request.contains("max_bytes"), "max_bytes requires configure");
  const auto limit = action == "configure" ? uint(request.at("max_bytes"), "max_bytes") : 0;
  require(limit <= 1024ULL * 1024 * 1024, "Representation cache is limited to 1 GiB");
  auto& state = cache();
  std::lock_guard<std::mutex> lock(state.mutex);
  if (action == "configure") {
    state.limit = limit;
    while (state.bytes > state.limit) state.evict();
  }
  if (action == "clear") {
    state.entries.clear();
    state.recent.clear();
    state.bytes = 0;
    state.hits = state.misses = state.evictions = 0;
  }
  return {{"max_bytes", state.limit},
          {"accounted_bytes", state.bytes},
          {"entries", state.entries.size()},
          {"hits", state.hits},
          {"misses", state.misses},
          {"evictions", state.evictions},
          {"scope",
           "process-local immutable representations; content, normalization semantics and "
           "implementation version keys"}};
}
}  // namespace graphmine::runtime
