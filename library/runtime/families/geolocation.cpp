#include "learning.hpp"

namespace graphmine::runtime {
namespace {
struct Location {
  double latitude, longitude;
};
Location location(const json::object& row) {
  const auto latitude = numeric::float64(row.at("latitude"), "latitude"),
             longitude = numeric::float64(row.at("longitude"), "longitude");
  require(latitude >= -90 && latitude <= 90 && longitude >= -180 && longitude <= 180,
          "Coordinates must be latitude [-90,90] and longitude [-180,180]");
  return {latitude, longitude};
}
double geodesic(const Location& a, const Location& b) {
  constexpr long double radians = 3.141592653589793238462643383279502884L / 180,
                        radius = 6371.0088L;
  const auto first = a.latitude * radians, second = b.latitude * radians;
  const auto dx = std::sin((second - first) / 2),
             dy = std::sin((b.longitude - a.longitude) * radians / 2);
  const auto h = std::clamp(dx * dx + std::cos(first) * std::cos(second) * dy * dy, 0.0L, 1.0L);
  return numeric::finite(2 * radius * std::atan2(std::sqrt(h), std::sqrt(1 - h)));
}
}  // namespace
json::object graph_geolocation(const Graph& graph, const json::object& args, const std::string&,
                               int, Work& work) {
  using namespace family_util;
  using namespace numeric;
  fields(args,
         {"method_family", "seed_locations", "method_definition", "hold_seeds_fixed",
          "training_definition"},
         {"method_family", "seed_locations", "method_definition"});
  choice(args, "method_family", "spatial_propagation", {"spatial_propagation"});
  require(!graph.directed(), "Geodesic medoid propagation requires undirected input");
  require(!args.contains("training_definition") || args.at("training_definition").is_null(),
          "training_definition does not apply to spatial propagation");
  const auto method = object(args.at("method_definition"), "method_definition");
  fields(method,
         {"objective", "metric", "max_iterations", "tolerance_km", "self_loops", "parallel_edges",
          "evaluation_locations"},
         {"objective"});
  choice(method, "objective", "seed_location_medoid_energy", {"seed_location_medoid_energy"});
  choice(method, "metric", "haversine_km", {"haversine_km"});
  choice(method, "self_loops", "reject", {"reject"});
  choice(method, "parallel_edges", "sum", {"sum"});
  const auto iterations = natural(method, "max_iterations", 100, 1);
  const auto tolerance =
      method.contains("tolerance_km") ? number(method.at("tolerance_km"), "tolerance_km") : 1e-6;
  require(tolerance >= 0, "tolerance_km must be nonnegative");
  const bool fixed = boolean(args, "hold_seeds_fixed", true);
  const auto seeds = object(args.at("seed_locations"), "seed_locations");
  fields(seeds, {"rows"}, {"rows"});
  require(seeds.at("rows").is_array(), "seed_locations.rows must be an array");
  const auto n = graph.vertex_count();
  std::vector<std::optional<std::size_t>> assignment(n);
  std::vector<bool> seeded(n, false);
  std::vector<Location> candidates;
  std::vector<VertexIndex> seed_vertices;
  for (const auto& raw : seeds.at("rows").as_array()) {
    const auto row = object(raw, "seed location");
    fields(row, {"vertex", "latitude", "longitude"}, {"vertex", "latitude", "longitude"});
    const auto v = graph.dense_index(external_id(row.at("vertex")));
    require(!seeded[v], "Seed vertices must be unique");
    seeded[v] = true;
    assignment[v] = candidates.size();
    candidates.push_back(location(row));
    seed_vertices.push_back(v);
  }
  for (const auto& edge : graph.canonical().edges)
    require(edge.source != edge.target, "Geolocation rejects loops");
  const auto normalized = edges(graph, true, work);
  std::vector<std::vector<std::pair<VertexIndex, double>>> neighbors(n);
  for (const auto& edge : normalized)
    if (edge.weight > 0) {
      const auto weight = finite(edge.weight.convert_to<long double>());
      require(weight > 0, "Positive propagation weight underflowed");
      neighbors[edge.u].emplace_back(edge.v, weight);
      neighbors[edge.v].emplace_back(edge.u, weight);
    }
  std::vector<Vertices> components;
  std::vector<std::size_t> component_of(n, SIZE_MAX);
  std::vector<std::vector<std::size_t>> choices;
  for (VertexIndex root = 0; root < n; ++root)
    if (component_of[root] == SIZE_MAX) {
      const auto component = components.size();
      Vertices vertices{root};
      component_of[root] = component;
      std::vector<std::size_t> located;
      for (std::size_t at = 0; at < vertices.size(); ++at) {
        const auto v = vertices[at];
        if (assignment[v]) located.push_back(*assignment[v]);
        for (const auto& [u, weight] : neighbors[v]) {
          work.tick();
          if (component_of[u] == SIZE_MAX) {
            component_of[u] = component;
            vertices.push_back(u);
          }
        }
      }
      components.push_back(vertices);
      choices.push_back(located);
    }
  // Initialize each supported component from a multi-source traversal. Seedless
  // components retain null locations instead of borrowing arbitrary coordinates.
  auto queue = seed_vertices;
  for (std::size_t at = 0; at < queue.size(); ++at)
    for (const auto& [v, weight] : neighbors[queue[at]]) {
      work.tick();
      if (!assignment[v]) {
        assignment[v] = assignment[queue[at]];
        queue.push_back(v);
      }
    }
  Matrix distances(candidates.size(), candidates.size(), work);
  for (std::size_t i = 0; i < candidates.size(); ++i)
    for (std::size_t j = i + 1; j < candidates.size(); ++j)
      distances(i, j) = distances(j, i) = geodesic(candidates[i], candidates[j]);
  auto energy = [&]() {
    long double result = 0;
    for (const auto& edge : normalized)
      if (assignment[edge.u] && assignment[edge.v]) {
        work.tick();
        result += edge.weight.convert_to<long double>() *
                  distances(*assignment[edge.u], *assignment[edge.v]);
      }
    return finite(result);
  };
  std::vector<double> history{energy()};
  bool converged = false;
  std::uint64_t completed = 0;
  double maximum_change = 0;
  for (std::uint64_t iteration = 0; iteration < iterations; ++iteration) {
    maximum_change = 0;
    bool changed = false;
    for (VertexIndex v = 0; v < n; ++v)
      if (assignment[v] && !(fixed && seeded[v])) {
        const auto previous = *assignment[v];
        auto best = previous;
        long double best_cost = 0;
        for (const auto& [u, weight] : neighbors[v])
          best_cost += weight * distances(previous, *assignment[u]);
        for (const auto candidate : choices[component_of[v]]) {
          long double cost = 0;
          for (const auto& [u, weight] : neighbors[v]) {
            work.tick();
            cost += weight * distances(candidate, *assignment[u]);
          }
          if (cost < best_cost) {
            best = candidate;
            best_cost = cost;
          }
        }
        if (best != previous) {
          changed = true;
          maximum_change = std::max(maximum_change, distances(previous, best));
          assignment[v] = best;
        }
      }
    ++completed;
    history.push_back(energy());
    require(history.back() <=
                history[history.size() - 2] + 1e-10 * std::max(1.0, history[history.size() - 2]),
            "Propagation energy increased beyond roundoff");
    if (!changed || maximum_change <= tolerance) {
      converged = true;
      break;
    }
  }
  json::array locations, confidence;
  for (VertexIndex v = 0; v < n; ++v) {
    json::object row{{"vertex", id_json(graph.external_id(v))}, {"location", nullptr}},
        dispersion{{"vertex", id_json(graph.external_id(v))},
                   {"weighted_mean_neighbor_distance_km", nullptr},
                   {"located_neighbor_count", neighbors[v].size()},
                   {"fixed_seed", fixed && seeded[v]}};
    if (assignment[v]) {
      const auto& point = candidates[*assignment[v]];
      row["location"] = json::object{{"latitude", point.latitude}, {"longitude", point.longitude}};
      long double total = 0, cost = 0;
      for (const auto& [u, weight] : neighbors[v]) {
        work.tick();
        total += weight;
        cost += weight * distances(*assignment[v], *assignment[u]);
      }
      if (total > 0) dispersion["weighted_mean_neighbor_distance_km"] = finite(cost / total);
    } else
      dispersion["located_neighbor_count"] = 0;
    locations.push_back(row);
    confidence.push_back(dispersion);
  }
  json::array errors;
  std::set<VertexIndex> evaluated;
  std::vector<double> values;
  const auto raw_evaluation = method.contains("evaluation_locations")
                                  ? method.at("evaluation_locations")
                                  : json::value(json::array{});
  require(raw_evaluation.is_array(), "evaluation_locations must be an array");
  for (const auto& raw : raw_evaluation.as_array()) {
    const auto row = object(raw, "evaluation location");
    fields(row, {"vertex", "latitude", "longitude"}, {"vertex", "latitude", "longitude"});
    const auto v = graph.dense_index(external_id(row.at("vertex")));
    require(!seeded[v] && evaluated.insert(v).second,
            "Evaluation vertices must be distinct and excluded from seeds");
    const auto truth = location(row);
    json::object error{{"vertex", row.at("vertex")}, {"geodesic_error_km", nullptr}};
    if (assignment[v]) {
      const auto distance = geodesic(candidates[*assignment[v]], truth);
      values.push_back(distance);
      error["geodesic_error_km"] = distance;
    }
    errors.push_back(error);
  }
  long double mean = 0;
  for (double v : values) mean += v;
  std::sort(values.begin(), values.end());
  const auto median = values.empty() ? 0
                      : values.size() % 2
                          ? values[values.size() / 2]
                          : (values[values.size() / 2 - 1] + values[values.size() / 2]) / 2;
  json::object metrics{
      {"held_out_count", errors.size()},
      {"resolved_count", values.size()},
      {"mean_geodesic_error_km",
       values.empty() ? json::value(nullptr) : json::value(finite(mean / values.size()))},
      {"median_geodesic_error_km", values.empty() ? json::value(nullptr) : json::value(median)},
      {"errors", errors}};
  work.output(2 * n + history.size() + errors.size());
  auto parameters = args;
  parameters["hold_seeds_fixed"] = fixed;
  parameters["training_definition"] = nullptr;
  auto result =
      output(parameters,
             {{"locations", locations},
              {"confidence", confidence},
              {"converged", converged},
              {"evaluation_metrics", metrics},
              {"propagation_summary",
               {{"objective",
                 "sum of positive edge weight times spherical geodesic distance; coordinates "
                 "restricted to seed locations in the same positive-weight component"},
                {"attained_energy_weighted_km", history.back()},
                {"energy_history", learning::array(history)},
                {"completed_iterations", completed},
                {"maximum_coordinate_change_km", maximum_change},
                {"earth_radius_km", 6371.0088},
                {"global_optimum_claimed", false}}}},
             {{"locations", result_port("vertex_locations", locations)},
              {"confidence", result_port("vertex_confidence", confidence)}},
             true, "heuristic");
  result["diagnostics"] = json::object{
      {"method", "sequential discrete geodesic median coordinate descent"},
      {"seedless_components", "unresolved"},
      {"confidence_interpretation", "neighbor dispersion; not a calibrated probability"},
      {"held_out_locations_used_for_fitting", false}};
  return result;
}
}  // namespace graphmine::runtime
