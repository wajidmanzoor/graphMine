#include "view_profiles.hpp"
#include "catalog_data.hpp"
#include <map>

namespace graphmine::runtime {
namespace {
std::map<std::string, ViewProfile>& profiles() {
  static std::map<std::string, ViewProfile> values;
  return values;
}
std::vector<std::string> names(std::initializer_list<const char*> values) {
  return {values.begin(), values.end()};
}
void observe(const ViewProfile& profile, Work& work, const ViewResult& view, bool hit, bool retained) {
  if (work.representations.size() >= 32) return;
  const auto key = work.input_fingerprint + ":" + implementation_sha256 + ":" +
                   view.snapshot_hash + ":standard-view-v2:" + view.canonical_spec;
  work.representations.push_back(json::object{
      {"kind", profile.spec.kind}, {"key", key}, {"hit", hit}, {"retained", retained},
      {"view_profile", profile.id}, {"view", json::parse(view.canonical_spec)},
      {"normalization", json::parse(view.normalization_json())}});
}
}
ViewProfile::ViewProfile(const char* name, std::initializer_list<const char*> operations,
                         const char* spec_json)
    : id(name), operations(names(operations)), spec(ViewSpec::from_json(spec_json)) {
  if (!profiles().emplace(id, *this).second) throw std::logic_error("Duplicate CPU view profile: " + id);
}
const ViewProfile& cpu_view_profile(const std::string& id) {
  const auto found = profiles().find(id);
  if (found == profiles().end()) throw std::invalid_argument("Unknown CPU view profile: " + id);
  return found->second;
}
json::array cpu_view_declarations() {
  json::array result;
  for (const auto& [id, profile] : profiles()) {
    json::array operations;
    for (const auto& operation : profile.operations) operations.push_back(json::value(operation));
    result.push_back(json::object{{"id", id}, {"backend", "cpp"}, {"operations", operations},
                                  {"view", json::parse(profile.spec.canonical_json())}});
  }
  return result;
}
MiningGraph adjacency_layout(const CsrView& view) {
  const CsrRows rows{view};
  MiningGraph output(rows.size());
  for (VertexIndex v = 0; v < rows.size(); ++v)
    output[v].assign(rows[v].begin(), rows[v].end());
  return output;
}
WeightedGraph weighted_layout(const CsrView& view) {
  const WeightedCsrRows rows{view};
  WeightedGraph output{std::vector<std::vector<Arc>>(rows.size()), view.directed};
  for (VertexIndex v = 0; v < rows.size(); ++v)
    output.rows[v].assign(rows[v].begin(), rows[v].end());
  return output;
}
std::shared_ptr<const ViewResult> consume_view(const Graph& graph, const ViewProfile& profile,
                                              Work& work, ViewBudget budget) {
  // Preserve each old adapter's candidate cost, including on cache hits.
  if (budget == ViewBudget::original_edges) work.tick(graph.edge_count());
  ViewBuildOptions options;
  if (budget == ViewBudget::record_edges)
    options.charge_original_edges = [&](std::uint64_t amount) { work.tick(amount); };
  options.charge = [&](std::uint64_t amount) {
    work.tick(budget == ViewBudget::weighted_adjacency ? amount : 0);
  };
  options.observe = [&](const ViewResult& view, bool hit, bool retained) {
    observe(profile,work,view,hit,retained);
  };
  try { return make_view(graph, profile.spec, options); }
  catch (const std::invalid_argument& error) {
    const std::string message = error.what();
    if (message == "Graph view: f64 sum overflows")
      throw Failure("invalid_input", "Aggregated edge weight overflowed");
    if (message == "Graph view: This operation requires nonnegative edge weights")
      throw Failure("invalid_input", "This operation requires nonnegative edge weights");
    throw;
  }
}
std::shared_ptr<const ViewResult> consume_view(const json::value& input, const ViewProfile& profile, Work& work) {
  ViewBuildOptions options;
  options.charge = [&](std::uint64_t) { work.tick(0); };
  options.observe = [&](const ViewResult& view, bool hit, bool retained) {
    observe(profile,work,view,hit,retained);
  };
  return make_view(ParsedViewInput{input},profile.spec,options);
}
}  // namespace graphmine::runtime
