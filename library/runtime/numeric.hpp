#pragma once

#include "family_util.hpp"

namespace graphmine::runtime::numeric {
struct Matrix {
  std::size_t rows = 0, cols = 0;
  std::vector<double> values;
  Matrix() = default;
  Matrix(std::size_t r, std::size_t c, Work& work) : rows(r), cols(c) {
    if (c && r > work.max_candidates / c)
      throw Failure("resource_limit", "Dense matrix exceeds candidate budget");
    work.tick(r * c);
    values.resize(r * c, 0);
  }
  double& operator()(std::size_t r, std::size_t c) { return values[r + rows * c]; }
  double operator()(std::size_t r, std::size_t c) const { return values[r + rows * c]; }
};
double finite(long double value);
double float64(const json::value& value, const char* context);
double tolerance(const json::object& args, const char* key = "tolerance", double initial = 1e-6);
Matrix transpose(const Matrix&, Work&);
Matrix multiply(const Matrix&, const Matrix&, Work&);
Matrix identity(std::size_t, Work&);
Matrix power(Matrix, std::uint64_t, Work&);
Matrix laplacian(const Graph&, bool normalized, Work&);
struct Eigen {
  std::vector<double> values;
  Matrix vectors;
};
Eigen symmetric_eigen(Matrix, Work&);
Matrix positive_solve(Matrix, Matrix, Work&);
double dot(const Matrix&, const Matrix&, Work&);
void check(const Matrix&);
}  // namespace graphmine::runtime::numeric
