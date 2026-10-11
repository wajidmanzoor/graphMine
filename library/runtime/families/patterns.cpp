#include <algorithm>
#include <limits>

#include "internal.hpp"

#ifdef GRAPHMINE_NATIVE_ORIGINAL_TRIANGLES
#include "graphmine/problems/triangle_counting.hpp"
#endif

namespace graphmine::runtime {
bool original_triangles_compiled(const std::string& backend) {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_TRIANGLES
  for (const auto& item : TriangleCounting::backends())
    if (item.id == backend && item.compiled) return true;
#endif
  return false;
}

json::object triangles(const Graph& graph, const json::object& args, const std::string& backend,
                       int device, Work& work) {
  fields(args, {"mode", "result_limit"});
  require(!graph.directed(), "triangle-counting requires an explicitly undirected graph");
  const auto mode = args.contains("mode") ? string(args.at("mode"), "mode") : "count";
  require(mode == "count" || mode == "enumerate", "mode must be count or enumerate");
  std::optional<std::uint64_t> limit;
  if (args.contains("result_limit") && !args.at("result_limit").is_null()) {
    limit = uint(args.at("result_limit"), "result_limit");
    require(*limit > 0 && mode == "enumerate",
            "result_limit requires enumerate mode and a positive integer");
  }
  std::optional<std::uint64_t> gpu_count;
  if (backend != "cpp") {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_TRIANGLES
    TriangleOptions options;
    options.backend = backend == "tot" ? TriangleBackend::tot : TriangleBackend::wetric;
    options.execution.device_ids = {device};
    const auto output = TriangleCounting(options).run(graph);
    if (!output.ok()) throw Failure("backend_failure", output.status().message());
    gpu_count = output.value().global_triangle_count;
#else
    throw Failure("backend_unavailable",
                  "Original triangle CUDA backends are not linked into this build");
#endif
  }
  std::uint64_t count = 0;
  json::array groups;
  if (!gpu_count || mode == "enumerate") {
    const auto adj = adjacency(graph, work);
    for (VertexIndex u = 0; u < graph.vertex_count(); ++u) {
      for (const auto v : adj[u]) {
        work.tick();
        if (v <= u) continue;
        auto a = std::upper_bound(adj[u].begin(), adj[u].end(), v);
        auto b = std::upper_bound(adj[v].begin(), adj[v].end(), v);
        while (a != adj[u].end() && b != adj[v].end()) {
          work.tick();
          if (*a < *b)
            ++a;
          else if (*b < *a)
            ++b;
          else {
            if (count == std::numeric_limits<std::uint64_t>::max())
              throw Failure("resource_limit", "Triangle count exceeds uint64");
            ++count;
            if (mode == "enumerate" && (!limit || groups.size() < *limit)) {
              work.output(groups.size() + 1);
              groups.push_back(
                  json::object{{"vertices", json::array{id_json(graph.external_id(u)),
                                                        id_json(graph.external_id(v)),
                                                        id_json(graph.external_id(*a))}}});
            }
            ++a;
            ++b;
          }
        }
      }
    }
    if (gpu_count && *gpu_count != count)
      throw Failure("correctness_mismatch",
                    "Native CPU materialization disagrees with original GPU count");
  } else
    count = *gpu_count;
  const bool complete = mode == "enumerate" && groups.size() == count;
  return {{"parameters",
           {{"mode", mode}, {"result_limit", limit ? json::value(*limit) : json::value(nullptr)}}},
          {"result", {{"count", count}, {"groups", groups}}},
          {"ports",
           {{"count", {{"type", "scalar"}, {"value", count}, {"complete", true}}},
            {"groups", {{"type", "vertex_groups"}, {"value", groups}, {"complete", complete}}}}},
          {"complete", mode == "count" || complete},
          {"quality", "exact"}};
}
}  // namespace graphmine::runtime
