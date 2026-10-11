#include "family_util.hpp"

namespace graphmine::runtime {
json::object persistent_homology(const Graph& graph, const json::object& args, const std::string&,
                                 int, Work& work) {
  using namespace family_util;
  fields(args, {"max_homology_dimension", "max_filtration", "field_prime"});
  require(!graph.directed(), "Flag persistence requires undirected input");
  const auto maximum = natural(args, "max_homology_dimension", 1),
             prime = natural(args, "field_prime", 2, 2);
  require(prime <= 46337, "field_prime exceeds supported modulus");
  for (std::uint64_t divisor = 2; divisor * divisor <= prime; ++divisor)
    require(prime % divisor != 0, "field_prime must be prime");
  std::optional<Exact> cutoff;
  if (args.contains("max_filtration") && !args.at("max_filtration").is_null()) {
    cutoff = exact_number(args.at("max_filtration"), "max_filtration");
    require(*cutoff >= 0, "max_filtration must be nonnegative");
  }
  const auto n = graph.vertex_count();
  std::map<std::pair<VertexIndex, VertexIndex>, Exact> weights;
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(edge.source != edge.target, "Persistence rejects self-loops");
    require(edge.weight && *edge.weight >= 0, "Every edge needs nonnegative filtration weight");
    auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u > v) std::swap(u, v);
    const Exact value(*edge.weight);
    auto [it, inserted] = weights.emplace(std::make_pair(u, v), value);
    if (!inserted && value < it->second) it->second = value;
  }
  MiningGraph adj(n);
  for (const auto& [ends, weight] : weights)
    if (!cutoff || weight <= *cutoff) {
      adj[ends.first].push_back(ends.second);
      adj[ends.second].push_back(ends.first);
    }
  for (auto& row : adj) std::sort(row.begin(), row.end());
  struct Simplex {
    Vertices vertices;
    Exact filtration;
  };
  std::vector<Simplex> simplices;
  const auto max_vertices = maximum >= n || n - maximum <= 2 ? n : maximum + 2;
  each_clique(adj, 1, max_vertices, work, [&](const Vertices& selected) {
    Exact filtration = 0;
    for (std::size_t i = 0; i < selected.size(); ++i)
      for (std::size_t j = i + 1; j < selected.size(); ++j) {
        work.tick();
        filtration = std::max(filtration, weights.at({selected[i], selected[j]}));
      }
    work.tick(selected.size());
    simplices.push_back({selected, filtration});
    return true;
  });
  std::sort(simplices.begin(), simplices.end(), [&](const auto& a, const auto& b) {
    work.tick();
    if (a.filtration != b.filtration) return a.filtration < b.filtration;
    if (a.vertices.size() != b.vertices.size()) return a.vertices.size() < b.vertices.size();
    return a.vertices < b.vertices;
  });
  std::map<Vertices, std::size_t> lookup;
  for (std::size_t i = 0; i < simplices.size(); ++i) lookup.emplace(simplices[i].vertices, i);
  using Column = std::map<std::size_t, std::uint64_t>;
  std::vector<Column> reduced(simplices.size());
  std::vector<std::optional<std::size_t>> owner(simplices.size()), death(simplices.size());
  auto inverse = [&](std::uint64_t value) {
    std::uint64_t exponent = prime - 2, result = 1;
    while (exponent) {
      work.tick();
      if (exponent & 1) result = result * value % prime;
      value = value * value % prime;
      exponent >>= 1;
    }
    return result;
  };
  for (std::size_t j = 0; j < simplices.size(); ++j) {
    auto& column = reduced[j];
    const auto& selected = simplices[j].vertices;
    if (selected.size() > 1)
      for (std::size_t i = 0; i < selected.size(); ++i) {
        work.tick(selected.size());
        auto face = selected;
        face.erase(face.begin() + i);
        const auto index = lookup.at(face);
        require(index < j, "Filtration violates face-before-coface ordering");
        column[index] = i % 2 ? prime - 1 : 1;
      }
    while (!column.empty() && owner[column.rbegin()->first]) {
      const auto& previous = reduced[*owner[column.rbegin()->first]];
      const auto multiplier = column.rbegin()->second * inverse(previous.rbegin()->second) % prime;
      for (const auto& [i, coefficient] : previous) {
        work.tick();
        const auto value = (column[i] + prime - multiplier * coefficient % prime) % prime;
        if (value)
          column[i] = value;
        else
          column.erase(i);
      }
    }
    if (!column.empty()) {
      const auto pivot = column.rbegin()->first;
      owner[pivot] = j;
      death[pivot] = j;
    }
  }
  struct Interval {
    std::size_t dimension;
    Exact birth;
    std::optional<Exact> death;
  };
  std::vector<Interval> intervals;
  std::size_t complex_dimension = 0;
  for (std::size_t i = 0; i < simplices.size(); ++i) {
    work.tick();
    const auto dim = simplices[i].vertices.size() - 1;
    complex_dimension = std::max(complex_dimension, dim);
    if (!reduced[i].empty() || dim > maximum) continue;
    const auto birth = simplices[i].filtration;
    if (death[i] && simplices[*death[i]].filtration == birth) continue;
    intervals.push_back(
        {dim, birth,
         death[i] ? std::optional<Exact>(simplices[*death[i]].filtration) : std::nullopt});
  }
  std::sort(intervals.begin(), intervals.end(), [](const auto& a, const auto& b) {
    if (a.dimension != b.dimension) return a.dimension < b.dimension;
    if (a.birth != b.birth) return a.birth < b.birth;
    if (!a.death || !b.death) return a.death.has_value() && !b.death.has_value();
    return *a.death < *b.death;
  });
  work.output(intervals.size());
  json::array rows;
  for (const auto& interval : intervals) {
    json::object row{{"dimension", interval.dimension}, {"death", nullptr}};
    exact_field(row, "birth", interval.birth);
    if (interval.death) exact_field(row, "death", *interval.death);
    rows.push_back(row);
  }
  auto result =
      output({{"max_homology_dimension", maximum},
              {"field_prime", prime},
              {"max_filtration",
               args.contains("max_filtration") ? args.at("max_filtration") : json::value(nullptr)}},
             {{"intervals", rows},
              {"essential_interval_convention",
               cutoff ? "right_censored_at_max_filtration; may be essential or die after cutoff"
                      : "essential_in_complete_flag_filtration"},
              {"coefficient_field", prime},
              {"interval_convention", "[birth, death); zero-length intervals omitted"},
              {"complete", true}},
             {{"intervals", result_port("persistence_intervals", rows)}});
  result["diagnostics"] = json::object{
      {"solver", "native_sparse_boundary_reduction_mod_prime"},
      {"simplex_count", simplices.size()},
      {"complex_dimension", simplices.empty() ? json::value(-1) : json::value(complex_dimension)},
      {"vertex_filtration", 0}};
  return result;
}
}  // namespace graphmine::runtime
