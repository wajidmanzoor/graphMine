#pragma once
#include "native_random.hpp"
#include "pattern_match.hpp"
#include "structured_input.hpp"

namespace graphmine::runtime::learning {
using family_util::Vertices;
using numeric::Matrix;
struct Training {
  std::uint64_t epochs = 200;
  double rate = 1, l2 = 0.001, tolerance = 1e-6;
};
Training training(const json::object&);
struct Fit {
  std::vector<double> parameters, gradient;
  std::vector<double> history;
  std::uint64_t iterations = 0;
  double loss = 0, initial_loss = 0, gradient_norm = 0;
  bool converged = false;
  std::string stopping_reason;
};
using Objective = std::function<double(const std::vector<double>&, std::vector<double>&)>;
Fit minimize(std::vector<double>, const Training&, const Objective&, Work&);
double sigmoid(double);
double softplus(double);
double random_initial(NativeRandom&);
json::array array(const std::vector<double>&);
json::array matrix(const Matrix&);
json::object summary(const Fit&, const Training&, const std::string&);
Matrix feature_rows(const std::vector<json::value>&, Work&);
Matrix propagate(const Graph&, Matrix, std::size_t, const std::string&, Work&);
struct Dataset {
  std::vector<ExternalId> ids;
  Matrix features;
  std::vector<std::string> splits;
  std::vector<json::value> targets;
  std::string id_field = "vertex";
};
void split(Dataset&, const json::object&, const json::object&, Work&);
// Fits the declared linear readout to already constructed graph features.
// Evaluation targets are accessed only after fitting has finished.
json::object supervised(Dataset, const std::string&, const json::object&, Work&);
}  // namespace graphmine::runtime::learning
