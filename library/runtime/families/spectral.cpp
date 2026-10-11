#include "numeric.hpp"

namespace graphmine::runtime {
json::object laplacian_eigenpairs(const Graph& graph, const json::object& args, const std::string&,
                                  int, Work& work) {
  using namespace family_util;
  using namespace numeric;
  fields(args, {"num_eigenpairs", "laplacian", "selection", "tolerance"}, {"num_eigenpairs"});
  const auto count = natural(args, "num_eigenpairs", 1, 1), n = graph.vertex_count();
  require(count <= n, "num_eigenpairs exceeds vertex count");
  const auto kind =
      choice(args, "laplacian", "combinatorial", {"combinatorial", "symmetric_normalized"});
  const auto selection = choice(args, "selection", "smallest", {"smallest", "largest"});
  const auto tol = tolerance(args);
  const auto matrix = laplacian(graph, kind == "symmetric_normalized", work);
  const auto spectrum = symmetric_eigen(matrix, work);
  const auto first = selection == "smallest" ? 0 : n - count;
  json::array values, vectors, residuals;
  for (std::size_t i = first; i < first + count; ++i) {
    values.push_back(spectrum.values[i]);
    long double residual = 0;
    for (std::size_t v = 0; v < n; ++v) {
      work.tick(n);
      long double product = 0;
      for (std::size_t u = 0; u < n; ++u)
        product += static_cast<long double>(matrix(v, u)) * spectrum.vectors(u, i);
      const auto difference =
          product - static_cast<long double>(spectrum.values[i]) * spectrum.vectors(v, i);
      residual += difference * difference;
    }
    const auto norm = finite(std::sqrt(residual));
    require(norm <= tol, "Eigenpair residual exceeds tolerance");
    residuals.push_back(norm);
  }
  long double orthogonality = 0;
  for (std::size_t i = first; i < first + count; ++i) {
    long double row = 0;
    for (std::size_t j = first; j < first + count; ++j) {
      work.tick(n);
      long double value = i == j ? -1 : 0;
      for (std::size_t v = 0; v < n; ++v)
        value += static_cast<long double>(spectrum.vectors(v, i)) * spectrum.vectors(v, j);
      row += std::abs(value);
    }
    orthogonality = std::max(orthogonality, row);
  }
  require(orthogonality <= tol, "Eigenvector orthogonality exceeds tolerance");
  work.output(n * count + count);
  for (std::size_t v = 0; v < n; ++v) {
    json::array row;
    for (std::size_t i = first; i < first + count; ++i) row.push_back(spectrum.vectors(v, i));
    vectors.push_back(row);
  }
  json::object data{{"eigenvalues", values},
                    {"eigenvectors", vectors},
                    {"vertex_order", ids(graph, all_vertices(graph))},
                    {"residual_norms", residuals},
                    {"orthogonality_error", finite(orthogonality)},
                    {"converged", true}};
  auto result = output({{"num_eigenpairs", count},
                        {"laplacian", kind},
                        {"selection", selection},
                        {"tolerance", tol}},
                       data, {{"eigenpairs", result_port("eigenpairs", data)}}, true, "numerical");
  result["diagnostics"] = json::object{
      {"solver", "native_LAPACK_dsyev"},
      {"absolute_tolerance", tol},
      {"arithmetic", "float64; independent residual recomputed with long-double accumulation"}};
  return result;
}

json::object signal_denoising(const Graph& graph, const json::object& args, const std::string&, int,
                              Work& work) {
  using namespace family_util;
  using namespace numeric;
  fields(args,
         {"observed_signal", "regularizer", "regularization_strength", "difference_order",
          "tolerance", "max_iterations"},
         {"observed_signal", "regularization_strength"});
  const auto regularizer = choice(args, "regularizer", "total_variation",
                                  {"total_variation", "trend_filtering", "laplacian_quadratic"});
  const auto strength = float64(args.at("regularization_strength"), "regularization_strength");
  require(strength >= 0, "Regularization strength must be nonnegative");
  const auto order = natural(args, "difference_order", 0),
             iterations = natural(args, "max_iterations", 1000, 1);
  const auto tol = tolerance(args);
  require(regularizer == "trend_filtering" || order == 0,
          "difference_order applies only to trend_filtering");
  const auto input = vertex_values(graph, args.at("observed_signal"), "observed_signal");
  const auto n = graph.vertex_count();
  const bool scalar = input.empty() || !input[0].is_array();
  const auto width = scalar ? 1 : input[0].as_array().size();
  require(width > 0, "Signal vectors must be nonempty");
  Matrix y(n, width, work);
  for (std::size_t v = 0; v < n; ++v) {
    if (scalar)
      y(v, 0) = float64(input[v], "signal");
    else {
      require(input[v].is_array() && input[v].as_array().size() == width,
              "Signal vectors must have equal width");
      for (std::size_t j = 0; j < width; ++j) y(v, j) = float64(input[v].as_array()[j], "signal");
    }
  }
  const auto matrix = laplacian(graph, false, work);
  Matrix x = y;
  double objective = 0, gap = 0, dual_objective = 0;
  std::string solver = "native_identity";
  std::uint64_t used_iterations = 0;
  if (n && strength > 0 && regularizer == "laplacian_quadratic") {
    auto system = matrix;
    for (auto& value : system.values) value = finite(static_cast<long double>(strength) * value);
    for (std::size_t v = 0; v < n; ++v)
      system(v, v) = finite(static_cast<long double>(system(v, v)) + 1);
    x = positive_solve(system, y, work);
    auto residual = multiply(system, x, work), difference = x;
    for (std::size_t i = 0; i < y.values.size(); ++i) {
      residual.values[i] -= y.values[i];
      difference.values[i] -= y.values[i];
    }
    gap = 0.5 * dot(residual, residual, work);
    const auto lx = multiply(matrix, x, work);
    objective =
        finite(0.5L * dot(difference, difference, work) + 0.5L * strength * dot(x, lx, work));
    solver = "native_LAPACK_dposv";
  } else if (n && strength > 0) {
    const auto normalized = edges(graph, true, work);
    Matrix difference(normalized.size(), n, work);
    for (std::size_t i = 0; i < normalized.size(); ++i) {
      const auto& edge = normalized[i];
      const auto weight = finite(edge.weight.convert_to<long double>());
      difference(i, edge.u) = regularizer == "total_variation" ? weight : std::sqrt(weight);
      difference(i, edge.v) = -difference(i, edge.u);
    }
    if (regularizer == "trend_filtering")
      difference = order % 2 ? power(matrix, order / 2 + 1, work)
                             : multiply(difference, power(matrix, order / 2, work), work);
    const auto transpose_d = transpose(difference, work), dy = multiply(difference, y, work);
    const auto lipschitz = dot(difference, difference, work);
    if (lipschitz > 0) {
      Matrix dual(difference.rows, width, work), momentum = dual;
      double acceleration = 1;
      bool converged = false;
      for (std::uint64_t iteration = 0; iteration < iterations; ++iteration) {
        auto transposed = multiply(transpose_d, momentum, work);
        for (std::size_t i = 0; i < transposed.values.size(); ++i)
          transposed.values[i] = y.values[i] - transposed.values[i];
        const auto gradient = multiply(difference, transposed, work);
        auto next = dual;
        for (std::size_t i = 0; i < next.values.size(); ++i)
          next.values[i] =
              std::clamp(momentum.values[i] + gradient.values[i] / lipschitz, -strength, strength);
        const auto correction = multiply(transpose_d, next, work);
        x = y;
        for (std::size_t i = 0; i < x.values.size(); ++i) x.values[i] -= correction.values[i];
        const auto dx = multiply(difference, x, work);
        long double penalty = 0;
        for (const auto value : dx.values) penalty += std::abs(value);
        const auto squared = dot(correction, correction, work);
        objective = finite(0.5L * squared + strength * penalty);
        dual_objective = finite(static_cast<long double>(dot(next, dy, work)) - 0.5L * squared);
        gap = finite(static_cast<long double>(objective) - dual_objective);
        require(gap >= -1e-10 * std::max(1.0, std::abs(objective)),
                "Denoising dual certificate exceeds primal objective");
        gap = std::max(0.0, gap);
        used_iterations = iteration + 1;
        if (gap <= tol) {
          converged = true;
          break;
        }
        const double next_acceleration = (1 + std::sqrt(1 + 4 * acceleration * acceleration)) / 2;
        for (std::size_t i = 0; i < next.values.size(); ++i)
          momentum.values[i] = next.values[i] + (acceleration - 1) / next_acceleration *
                                                    (next.values[i] - dual.values[i]);
        dual = std::move(next);
        acceleration = next_acceleration;
      }
      if (!converged)
        throw Failure("numerical_failure",
                      "Denoising did not meet objective-gap tolerance within max_iterations");
      solver = "native_accelerated_box_constrained_dual";
    }
  }
  require(std::isfinite(gap) && gap <= tol,
          "Denoising objective-gap certificate exceeds tolerance");
  check(x);
  work.output(n * width);
  json::array rows;
  for (std::size_t v = 0; v < n; ++v) {
    json::array values;
    for (std::size_t j = 0; j < width; ++j) values.push_back(x(v, j));
    rows.push_back(json::object{{"vertex", id_json(graph.external_id(v))},
                                {"value", scalar ? json::value(x(v, 0)) : json::value(values)}});
  }
  auto result =
      output({{"observed_signal", args.at("observed_signal")},
              {"regularizer", regularizer},
              {"regularization_strength", strength},
              {"difference_order", order},
              {"tolerance", tol},
              {"max_iterations", iterations}},
             {{"estimated_signal", rows}, {"objective_value", objective}, {"converged", true}},
             {{"signal", result_port("vertex_signal", rows)}}, true, "numerical");
  result["diagnostics"] = json::object{
      {"solver", solver},
      {"objective_gap_bound", gap},
      {"solution_l2_error_bound", std::sqrt(2 * gap)},
      {"dual_objective", dual_objective},
      {"iterations", used_iterations},
      {"penalty",
       regularizer == "laplacian_quadratic" ? "0.5 * strength * trace(X.T L X)"
       : regularizer == "total_variation"
           ? "strength * ||diag(weight) B X||_1"
           : "strength * ||D X||_1; D=B_weighted L^(k/2) for even k, L^((k+1)/2) for odd k"}};
  return result;
}
}  // namespace graphmine::runtime
