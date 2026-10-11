#include <tuple>

#include "native_random.hpp"
#include "numeric.hpp"

namespace graphmine::runtime {
json::object force_layout(const Graph& graph, const json::object& args, const std::string&, int,
                          Work& work) {
  using namespace family_util;
  using namespace numeric;
  fields(args, {"dimensions", "force_model", "weight_mode", "iterations", "random_seed",
                "initial_positions", "optimal_distance", "force_tolerance", "solution_quality"});
  const auto dimensions = natural(args, "dimensions", 2);
  require(dimensions == 2 || dimensions == 3, "dimensions must be two or three");
  const auto model = choice(args, "force_model", "fruchterman_reingold", {"fruchterman_reingold"});
  const auto weight_mode = choice(args, "weight_mode", "unweighted", {"unweighted", "edge_weight"});
  const auto quality =
      choice(args, "solution_quality", "approximate", {"approximate", "converged"});
  const auto iterations = natural(args, "iterations", 50), seed = natural(args, "random_seed", 0);
  const auto tol = tolerance(args, "force_tolerance");
  const auto n = graph.vertex_count();
  const double k = args.contains("optimal_distance") && !args.at("optimal_distance").is_null()
                       ? float64(args.at("optimal_distance"), "optimal_distance")
                       : 1 / std::sqrt(std::max<std::size_t>(1, n));
  require(k > 0, "optimal_distance must be positive");
  Matrix weights(n, n, work), positions(n, dimensions, work);
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    require(weight_mode == "unweighted" || edge.weight.has_value(),
            "Weighted layout requires every edge weight");
    const double value = weight_mode == "unweighted" ? 1 : *edge.weight;
    require(value >= 0, "Layout weights must be nonnegative");
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    weights(u, v) = weights(v, u) =
        weight_mode == "unweighted" ? 1 : finite(static_cast<long double>(weights(u, v)) + value);
  }
  if (args.contains("initial_positions") && !args.at("initial_positions").is_null()) {
    const auto rows = vertex_values(graph, args.at("initial_positions"), "initial_positions");
    for (std::size_t v = 0; v < n; ++v) {
      require(rows[v].is_array() && rows[v].as_array().size() == dimensions,
              "Initial positions must match dimensions");
      for (std::size_t j = 0; j < dimensions; ++j)
        positions(v, j) = float64(rows[v].as_array()[j], "initial coordinate");
    }
  } else {
    NativeRandom random(json::object{{"random_seed", seed}});
    for (auto& coordinate : positions.values) {
      work.tick();
      coordinate = std::ldexp(static_cast<double>(random.engine() >> 11), -53);
    }
  }
  auto forces = [&](const Matrix& pos) {
    Matrix force(n, dimensions, work);
    long double energy = 0;
    const long double floor = 0.01L;
    for (std::size_t u = 0; u < n; ++u)
      for (std::size_t v = u + 1; v < n; ++v) {
        work.tick(dimensions);
        long double squared = 0;
        for (std::size_t j = 0; j < dimensions; ++j) {
          const long double delta = static_cast<long double>(pos(u, j)) - pos(v, j);
          squared += delta * delta;
        }
        const auto distance = std::sqrt(squared), clipped = std::max(distance, floor);
        const long double k2 = static_cast<long double>(k) * k;
        const auto repulsion =
            distance >= floor ? -k2 * std::log(clipped)
                              : -k2 * std::log(floor) + 0.5L * k2 * (1 - squared / (floor * floor));
        const auto attraction = distance >= floor
                                    ? distance * squared / (3 * k)
                                    : floor * squared / (2 * k) - floor * floor * floor / (6 * k);
        energy += repulsion + weights(u, v) * attraction;
        const auto coefficient = k2 / (clipped * clipped) - weights(u, v) * clipped / k;
        for (std::size_t j = 0; j < dimensions; ++j) {
          const auto value = (static_cast<long double>(pos(u, j)) - pos(v, j)) * coefficient;
          force(u, j) = finite(static_cast<long double>(force(u, j)) + value);
          force(v, j) = finite(static_cast<long double>(force(v, j)) - value);
        }
      }
    double residual = 0;
    for (std::size_t v = 0; v < n; ++v) {
      long double squared = 0;
      for (std::size_t j = 0; j < dimensions; ++j)
        squared += static_cast<long double>(force(v, j)) * force(v, j);
      residual = std::max(residual, finite(std::sqrt(squared)));
    }
    return std::make_tuple(std::move(force), finite(energy), residual);
  };
  long double span = 0;
  for (std::size_t j = 0; j < dimensions && n; ++j) {
    double lower = positions(0, j), upper = lower;
    for (std::size_t v = 1; v < n; ++v) {
      lower = std::min(lower, positions(v, j));
      upper = std::max(upper, positions(v, j));
    }
    span = std::max(span, static_cast<long double>(upper) - lower);
  }
  const long double initial_temperature = span * 0.1L;
  const auto count = n <= 1 ? 0 : iterations;
  for (std::uint64_t iteration = 0; iteration < count; ++iteration) {
    const auto [force, energy, residual] = forces(positions);
    const long double temperature =
        initial_temperature *
        (1 - static_cast<long double>(iteration) / (static_cast<long double>(iterations) + 1));
    for (std::size_t v = 0; v < n; ++v) {
      work.tick(dimensions);
      long double squared = 0;
      for (std::size_t j = 0; j < dimensions; ++j)
        squared += static_cast<long double>(force(v, j)) * force(v, j);
      const auto norm = std::sqrt(squared), denominator = norm < 0.01L ? 0.1L : norm;
      for (std::size_t j = 0; j < dimensions; ++j)
        positions(v, j) = finite(positions(v, j) + temperature * force(v, j) / denominator);
    }
  }
  const auto [force, energy, residual] = forces(positions);
  const bool converged = residual <= tol;
  require(quality != "converged" || converged,
          "Fixed layout iterations did not meet force_tolerance");
  work.output(n * dimensions);
  json::array rows;
  for (std::size_t v = 0; v < n; ++v) {
    json::array coordinates;
    for (std::size_t j = 0; j < dimensions; ++j) coordinates.push_back(positions(v, j));
    rows.push_back(
        json::object{{"vertex", id_json(graph.external_id(v))}, {"coordinates", coordinates}});
  }
  auto result = output(
      {{"dimensions", dimensions},
       {"force_model", model},
       {"weight_mode", weight_mode},
       {"iterations", iterations},
       {"random_seed", seed},
       {"initial_positions",
        args.contains("initial_positions") ? args.at("initial_positions") : json::value(nullptr)},
       {"optimal_distance", k},
       {"force_tolerance", tol},
       {"solution_quality", quality}},
      {{"vertex_positions", rows},
       {"dimensions", dimensions},
       {"final_energy", energy},
       {"converged", converged},
       {"iterations_run", count},
       {"max_force_norm", residual}},
      {{"positions", result_port("vertex_positions", rows)}}, true, "heuristic");
  result["diagnostics"] = json::object{
      {"solver", "native_Fruchterman_Reingold"},
      {"distance_floor", 0.01},
      {"optimal_distance", k},
      {"force_tolerance", tol},
      {"convergence_criterion", "maximum uncooled force norm <= force_tolerance"},
      {"optimality_claimed", false},
      {"rescaled_after_iteration", false},
      {"initial_temperature", "one tenth of maximum coordinate span across all dimensions"},
      {"energy_convention",
       "pairwise integrated distance-clipped Fruchterman-Reingold potential; continuous at 0.01"},
      {"random_generator", "mt19937_64"}};
  return result;
}
}  // namespace graphmine::runtime
