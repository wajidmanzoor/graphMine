// Test-only interposition: verify the actual arrays supplied during all existing
// oracle suites against the frozen pre-migration code, including generated data.
#include "legacy_normalizers.hpp"
#include "../views_internal.hpp"
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#include <cstring>
#include <cstdlib>
#include <iostream>

namespace {
using namespace graphmine;
namespace rt = graphmine::runtime;
[[noreturn]] void mismatch(const char* message) {
  std::cerr << "NORMALIZER GOLDEN FAILURE: " << message << '\n';
  std::abort();
}
template<class T> void bytes(const std::vector<T>& a, const std::vector<T>& b) {
  if (a.size() != b.size() || (!a.empty() && std::memcmp(a.data(), b.data(), a.size()*sizeof(T))))
    mismatch("array bytes differ");
}
template<class T> T real(const char* name) {
  auto function = reinterpret_cast<T>(dlsym(RTLD_NEXT, name));
  if (!function) mismatch(dlerror());
  return function;
}
void record(const Graph& graph, const std::string& profile, bool rejected = false) {
  const char* path = std::getenv("GRAPHMINE_NORMALIZER_AUDIT");
  if (!path) mismatch("audit output path is required");
  const auto row = rt::json::serialize(rt::json::object{
      {"dataset", graph.canonical().graph.id}, {"snapshot", view_detail::graph_hash(graph)},
      {"vertices", graph.vertex_count()}, {"edges", graph.edge_count()},
      {"profile", profile}, {"rejection", rejected}, {"equal", true}}) + "\n";
  const int fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0600);
  if (fd < 0 || flock(fd, LOCK_EX)) mismatch("cannot open audit output");
  if (write(fd, row.data(), row.size()) != static_cast<ssize_t>(row.size())) mismatch("cannot write audit output");
  flock(fd, LOCK_UN); close(fd);
}
}
namespace graphmine {
UndirectedGraphView Graph::simple_undirected(UndirectedProjectionOptions options) const {
  using Function = UndirectedGraphView(*)(const Graph*, UndirectedProjectionOptions);
  static const auto call = real<Function>("_ZNK9graphmine5Graph17simple_undirectedENS_27UndirectedProjectionOptionsE");
  const auto expected = legacy_test::simple(*this, options);
  auto actual = call(this, options);
  bytes(expected.csr.offsets, actual.csr.offsets);
  bytes(expected.csr.neighbors, actual.csr.neighbors);
  if (expected.normalization.directed_projection_applied != actual.normalization.directed_projection_applied ||
      expected.normalization.self_loops_removed != actual.normalization.self_loops_removed ||
      expected.normalization.parallel_edges_collapsed != actual.normalization.parallel_edges_collapsed)
    mismatch("simple normalization counts differ");
  record(*this, "simple_undirected");
  return actual;
}
namespace runtime {
WeightedGraph weighted_graph(const Graph& graph, bool weighted, bool nonnegative,
    const std::string& aggregation, const std::string& direction, Work& work) {
  using Function = WeightedGraph(*)(const Graph&, bool, bool, const std::string&, const std::string&, Work&);
  static const auto call = real<Function>("_ZN9graphmine7runtime14weighted_graphERKNS_5GraphEbbRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESB_RNS0_4WorkE");
  auto reference_work = work;
  reference_work.timeout_seconds = std::numeric_limits<double>::infinity();
  std::optional<WeightedGraph> expected;
  std::string failure;
  try { expected = legacy_test::weighted(graph, weighted, nonnegative, aggregation, direction, reference_work); }
  catch (const std::exception& error) { failure = error.what(); }
  const auto profile = std::string(weighted ? "weighted:" : "unit:") +
      (nonnegative ? "nonnegative:" : "signed:") + aggregation + ":" + direction;
  WeightedGraph actual;
  try { actual = call(graph, weighted, nonnegative, aggregation, direction, work); }
  catch (const std::exception& error) {
    if (std::string(error.what()).find("deadline") != std::string::npos) throw;
    if (expected || failure != error.what()) mismatch("weighted rejection differs");
    record(graph, profile, true);
    throw;
  }
  if (!expected || expected->directed != actual.directed || expected->rows.size() != actual.rows.size())
    mismatch("weighted shape or admission differs");
  if (reference_work.candidates != work.candidates) mismatch("candidate cost differs");
  for (std::size_t u = 0; u < actual.rows.size(); ++u) {
    if (expected->rows[u].size() != actual.rows[u].size()) mismatch("weighted row size differs");
    for (std::size_t i = 0; i < actual.rows[u].size(); ++i) {
      const auto& a = expected->rows[u][i]; const auto& b = actual.rows[u][i];
      if (a.target != b.target || std::memcmp(&a.weight, &b.weight, sizeof(double)))
        mismatch("weighted target/weight bytes differ");
    }
  }
  record(graph, profile);
  return actual;
}
}  // namespace runtime
}  // namespace graphmine
