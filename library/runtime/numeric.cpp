#include "numeric.hpp"

#include <climits>

// Native LAPACK LP64 interfaces. No Python interpreter or Python extension is
// loaded. Matrices are column-major and every solver result is checked by its
// caller against the original objective or eigen-equations.
extern "C" {
void dsyev_(const char*, const char*, const int*, double*, const int*, double*, double*, const int*,
            int*);
void dposv_(const char*, const int*, const int*, double*, const int*, double*, const int*, int*);
}
namespace graphmine::runtime::numeric {
double finite(long double value) {
  const double converted = value;
  require(std::isfinite(converted), "Numerical result exceeded finite float64 range");
  return converted;
}
double float64(const json::value& value, const char* context) {
  const auto result = number(value, context);
  if (value.is_int64() || value.is_uint64())
    require(Exact(result) == exact_number(value, context),
            std::string(context) + " loses integer precision in float64");
  return result;
}
double tolerance(const json::object& args, const char* key, double initial) {
  const auto value = args.contains(key) ? number(args.at(key), key) : initial;
  require(value > 0, std::string(key) + " must be positive");
  return value;
}
void check(const Matrix& matrix) {
  for (const auto value : matrix.values)
    require(std::isfinite(value), "Numerical matrix contains a nonfinite value");
}
Matrix transpose(const Matrix& matrix, Work& work) {
  Matrix result(matrix.cols, matrix.rows, work);
  for (std::size_t i = 0; i < matrix.rows; ++i)
    for (std::size_t j = 0; j < matrix.cols; ++j) result(j, i) = matrix(i, j);
  return result;
}
Matrix multiply(const Matrix& a, const Matrix& b, Work& work) {
  require(a.cols == b.rows, "Incompatible native matrix dimensions");
  Matrix result(a.rows, b.cols, work);
  for (std::size_t j = 0; j < b.cols; ++j)
    for (std::size_t i = 0; i < a.rows; ++i) {
      work.tick(a.cols);
      long double value = 0;
      for (std::size_t k = 0; k < a.cols; ++k) value += static_cast<long double>(a(i, k)) * b(k, j);
      result(i, j) = finite(value);
    }
  return result;
}
Matrix identity(std::size_t n, Work& work) {
  Matrix result(n, n, work);
  for (std::size_t i = 0; i < n; ++i) result(i, i) = 1;
  return result;
}
Matrix power(Matrix matrix, std::uint64_t exponent, Work& work) {
  require(matrix.rows == matrix.cols, "Matrix power requires a square matrix");
  auto result = identity(matrix.rows, work);
  while (exponent) {
    if (exponent & 1) result = multiply(result, matrix, work);
    exponent >>= 1;
    if (exponent) matrix = multiply(matrix, matrix, work);
  }
  return result;
}
Matrix laplacian(const Graph& graph, bool normalized, Work& work) {
  require(!graph.directed(), "Laplacian requires undirected input");
  for (const auto& edge : graph.canonical().edges)
    require(edge.source != edge.target, "Laplacian profiles reject self-loops");
  const auto edges = family_util::edges(graph, true, work);
  const auto n = graph.vertex_count();
  Matrix result(n, n, work);
  std::vector<long double> degree(n, 0);
  for (const auto& edge : edges) {
    work.tick();
    const auto weight = finite(edge.weight.convert_to<long double>());
    require(edge.weight == 0 || weight > 0, "Positive weight underflows float64");
    if (denominator(edge.weight) == 1)
      require(Exact(weight) == edge.weight,
              "Aggregated integer edge weight loses float64 precision");
    result(edge.u, edge.v) = result(edge.v, edge.u) = -weight;
    degree[edge.u] += weight;
    degree[edge.v] += weight;
  }
  for (std::size_t v = 0; v < n; ++v) result(v, v) = finite(degree[v]);
  if (normalized)
    for (std::size_t u = 0; u < n; ++u)
      for (std::size_t v = 0; v < n; ++v) {
        work.tick();
        result(u, v) = degree[u] > 0 && degree[v] > 0
                           ? finite(result(u, v) / std::sqrt(degree[u]) / std::sqrt(degree[v]))
                           : 0;
      }
  check(result);
  return result;
}
void solver_budget(std::size_t n, Work& work) {
  require(n <= INT_MAX, "Matrix exceeds native LAPACK LP64 dimension");
  if (n && (n > work.max_candidates / n || n > work.max_candidates / n / n))
    throw Failure("resource_limit", "Dense solver exceeds candidate budget");
  work.tick(n * n * n);
}
Eigen symmetric_eigen(Matrix matrix, Work& work) {
  require(matrix.rows == matrix.cols, "Symmetric eigensolver requires square input");
  solver_budget(matrix.rows, work);
  check(matrix);
  const int n = matrix.rows, lda = std::max(n, 1);
  std::vector<double> values(n);
  if (!n) return {values, std::move(matrix)};
  const char job = 'V', upper = 'U';
  int info = 0, length = -1;
  double query = 0;
  dsyev_(&job, &upper, &n, matrix.values.data(), &lda, values.data(), &query, &length, &info);
  require(info == 0 && std::isfinite(query) && query >= 1 && query <= INT_MAX,
          "LAPACK workspace query failed");
  length = static_cast<int>(query);
  work.tick(length);
  std::vector<double> workspace(length);
  dsyev_(&job, &upper, &n, matrix.values.data(), &lda, values.data(), workspace.data(), &length,
         &info);
  work.tick(0);
  if (info != 0) throw Failure("numerical_failure", "Native LAPACK eigensolver did not converge");
  check(matrix);
  for (const auto value : values) finite(value);
  return {std::move(values), std::move(matrix)};
}
Matrix positive_solve(Matrix matrix, Matrix rhs, Work& work) {
  require(matrix.rows == matrix.cols && matrix.rows == rhs.rows,
          "Invalid positive system dimensions");
  solver_budget(matrix.rows, work);
  check(matrix);
  check(rhs);
  require(rhs.cols <= INT_MAX, "Too many right-hand sides");
  if (!matrix.rows || !rhs.cols) return rhs;
  const int n = matrix.rows, count = rhs.cols, lda = n;
  int info = 0;
  const char upper = 'U';
  dposv_(&upper, &n, &count, matrix.values.data(), &lda, rhs.values.data(), &lda, &info);
  work.tick(0);
  if (info != 0) throw Failure("numerical_failure", "Native positive-definite system solve failed");
  check(rhs);
  return rhs;
}
double dot(const Matrix& a, const Matrix& b, Work& work) {
  require(a.rows == b.rows && a.cols == b.cols, "Incompatible dot-product dimensions");
  work.tick(a.values.size());
  long double result = 0;
  for (std::size_t i = 0; i < a.values.size(); ++i)
    result += static_cast<long double>(a.values[i]) * b.values[i];
  return finite(result);
}
}  // namespace graphmine::runtime::numeric
