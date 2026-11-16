#include "representation_cache.hpp"

#include <list>
#include <mutex>
#include <unordered_map>
#include "../src/core/representation_store.hpp"

#include "catalog_data.hpp"

namespace graphmine::runtime {
using representation_store::lookup;
using representation_store::insert;
namespace {
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

json::object representation_cache_request(const json::object& request) {
  fields(request, {"command", "action", "max_bytes"}, {"command"});
  const auto action =
      request.contains("action") ? string(request.at("action"), "action") : "status";
  require(action == "status" || action == "clear" || action == "configure", "Unknown cache action");
  require(action == "configure" || !request.contains("max_bytes"), "max_bytes requires configure");
  const auto limit = action == "configure" ? uint(request.at("max_bytes"), "max_bytes") : 0;
  require(limit <= 1024ULL * 1024 * 1024, "Representation cache is limited to 1 GiB");
  const auto state = representation_store::control(
      action == "configure" ? std::optional<std::size_t>(limit) : std::nullopt, action == "clear");
  return {{"max_bytes", state.limit},
          {"accounted_bytes", state.bytes},
          {"entries", state.entries},
          {"hits", state.hits},
          {"misses", state.misses},
          {"evictions", state.evictions},
          {"scope",
           "process-local immutable representations; content, normalization semantics and "
           "implementation version keys"}};
}
}  // namespace graphmine::runtime
