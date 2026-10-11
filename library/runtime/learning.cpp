#include "learning.hpp"

#include <array>

namespace graphmine::runtime::learning {
Training training(const json::object& args) {
  Training result;
  family_util::choice(args, "optimizer", "gradient_descent", {"gradient_descent"});
  result.epochs = family_util::natural(args, "epochs", 200, 1);
  result.rate = args.contains("learning_rate")
                    ? numeric::float64(args.at("learning_rate"), "learning_rate")
                    : 1;
  result.l2 = args.contains("l2") ? numeric::float64(args.at("l2"), "l2") : 0.001;
  result.tolerance = numeric::tolerance(args);
  require(result.rate > 0 && result.l2 >= 0, "learning_rate must be positive and l2 nonnegative");
  return result;
}
double sigmoid(double x) {
  if (x >= 0) return 1 / (1 + std::exp(-x));
  const auto e = std::exp(x);
  return e / (1 + e);
}
double softplus(double x) { return std::max(x, 0.0) + std::log1p(std::exp(-std::abs(x))); }
double random_initial(NativeRandom& random) {
  return (static_cast<double>(random.engine() >> 11) * 0x1.0p-53 - 0.5) * 0.02;
}
json::array array(const std::vector<double>& values) {
  json::array result;
  for (const auto v : values) result.push_back(v);
  return result;
}
json::array matrix(const Matrix& values) {
  json::array result;
  for (std::size_t i = 0; i < values.rows; ++i) {
    json::array row;
    for (std::size_t j = 0; j < values.cols; ++j) row.push_back(values(i, j));
    result.push_back(row);
  }
  return result;
}
Fit minimize(std::vector<double> parameters, const Training& configuration,
             const Objective& objective, Work& work) {
  Fit result;
  result.parameters = std::move(parameters);
  work.tick(result.parameters.size());
  result.gradient.resize(result.parameters.size());
  auto evaluate = [&](const std::vector<double>& values, std::vector<double>& gradient) {
    work.tick(values.size());
    std::fill(gradient.begin(), gradient.end(), 0);
    const auto loss = objective(values, gradient);
    require(std::isfinite(loss) && std::all_of(gradient.begin(), gradient.end(),
                                               [](double v) { return std::isfinite(v); }),
            "Learning objective or gradient is not finite");
    return loss;
  };
  result.loss = result.initial_loss = evaluate(result.parameters, result.gradient);
  result.history.push_back(result.loss);
  for (std::uint64_t iteration = 0; iteration < configuration.epochs; ++iteration) {
    long double norm_squared = 0;
    for (double g : result.gradient) norm_squared += static_cast<long double>(g) * g;
    result.gradient_norm = numeric::finite(std::sqrt(norm_squared));
    if (result.gradient_norm <= configuration.tolerance) {
      result.converged = true;
      result.stopping_reason = "gradient_tolerance";
      break;
    }
    double step = configuration.rate;
    std::vector<double> candidate(result.parameters.size()), gradient(result.parameters.size());
    bool accepted = false;
    for (std::size_t attempt = 0; attempt < 60; ++attempt) {
      work.tick(candidate.size());
      bool finite = true, changed = false;
      for (std::size_t i = 0; i < candidate.size(); ++i) {
        candidate[i] = result.parameters[i] - step * result.gradient[i];
        finite = finite && std::isfinite(candidate[i]);
        changed = changed || candidate[i] != result.parameters[i];
      }
      if (!changed) break;
      if (finite) {
        const auto value = evaluate(candidate, gradient);
        if (value <= result.loss - 0.0001L * step * norm_squared) {
          result.parameters = std::move(candidate);
          result.gradient = std::move(gradient);
          result.loss = value;
          accepted = true;
          break;
        }
      }
      step /= 2;
    }
    if (!accepted) {
      result.stopping_reason = "numerical_line_search_limit";
      break;
    }
    ++result.iterations;
    result.history.push_back(result.loss);
  }
  long double norm_squared = 0;
  for (double value : result.gradient) norm_squared += static_cast<long double>(value) * value;
  result.gradient_norm = numeric::finite(std::sqrt(norm_squared));
  result.converged = result.gradient_norm <= configuration.tolerance;
  if (result.converged)
    result.stopping_reason = "gradient_tolerance";
  else if (result.stopping_reason.empty())
    result.stopping_reason = "epoch_budget";
  return result;
}
json::object summary(const Fit& fit, const Training& configuration, const std::string& objective) {
  return {{"objective", objective},
          {"initial_loss", fit.initial_loss},
          {"attained_loss", fit.loss},
          {"loss_history", array(fit.history)},
          {"gradient_norm", fit.gradient_norm},
          {"converged", fit.converged},
          {"stopping_reason", fit.stopping_reason},
          {"completed_epochs", fit.iterations},
          {"epoch_budget", configuration.epochs},
          {"learning_rate", configuration.rate},
          {"l2", configuration.l2},
          {"tolerance", configuration.tolerance},
          {"optimizer", "full-batch gradient descent with Armijo backtracking"},
          {"global_optimum_claimed", false}};
}
Matrix feature_rows(const std::vector<json::value>& rows, Work& work) {
  require(!rows.empty(), "Learning requires at least one feature row");
  require(rows[0].is_array() && !rows[0].as_array().empty(),
          "Features must be nonempty numeric arrays");
  const auto dimension = rows[0].as_array().size();
  Matrix result(rows.size(), dimension, work);
  for (std::size_t i = 0; i < rows.size(); ++i) {
    require(rows[i].is_array() && rows[i].as_array().size() == dimension,
            "All feature rows must have equal width");
    for (std::size_t j = 0; j < dimension; ++j)
      result(i, j) = numeric::float64(rows[i].as_array()[j], "feature");
  }
  return result;
}
Matrix propagate(const Graph& graph, Matrix features, std::size_t layers,
                 const std::string& direction, Work& work) {
  require(
      direction == "incoming" || direction == "outgoing" || direction == "undirected_projection",
      "Invalid propagation direction");
  MiningGraph neighbors(graph.vertex_count());
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    if (u == v) continue;
    if (!graph.directed() || direction == "undirected_projection") {
      neighbors[u].push_back(v);
      neighbors[v].push_back(u);
    } else if (direction == "incoming")
      neighbors[v].push_back(u);
    else
      neighbors[u].push_back(v);
  }
  for (VertexIndex v = 0; v < neighbors.size(); ++v) {
    neighbors[v].push_back(v);
    std::sort(neighbors[v].begin(), neighbors[v].end());
    neighbors[v].erase(std::unique(neighbors[v].begin(), neighbors[v].end()), neighbors[v].end());
  }
  for (std::size_t layer = 0; layer < layers; ++layer) {
    Matrix next(features.rows, features.cols, work);
    for (std::size_t v = 0; v < features.rows; ++v)
      for (std::size_t c = 0; c < features.cols; ++c) {
        long double sum = 0;
        for (const auto u : neighbors[v]) {
          work.tick();
          sum += features(u, c);
        }
        next(v, c) = numeric::finite(sum / neighbors[v].size());
      }
    features = std::move(next);
  }
  return features;
}
void split(Dataset& data, const json::object& specification, const json::object& training_labels,
           Work& work) {
  fields(specification,
         {"train", "validation", "test", "policy", "validation_labels", "test_labels"}, {"train"});
  family_util::choice(specification, "policy", "transductive", {"transductive"});
  std::map<ExternalId, std::size_t> indices;
  for (std::size_t i = 0; i < data.ids.size(); ++i)
    require(indices.emplace(data.ids[i], i).second, "Duplicate learning entity ID");
  data.splits.assign(data.ids.size(), "inference");
  data.targets.resize(data.ids.size());
  std::set<std::size_t> assigned, labeled;
  auto index = [&](const json::value& raw) {
    const auto it = indices.find(external_id(raw));
    require(it != indices.end(), "Unknown learning split/label ID");
    return it->second;
  };
  for (const auto* name : {"train", "validation", "test"})
    if (specification.contains(name)) {
      require(specification.at(name).is_array(), "Learning splits must be arrays");
      for (const auto& raw : specification.at(name).as_array()) {
        work.tick();
        const auto i = index(raw);
        require(assigned.insert(i).second,
                "Learning splits must be disjoint and contain distinct IDs");
        data.splits[i] = name;
      }
    }
  fields(training_labels, {"rows"}, {"rows"});
  auto labels = [&](const json::value& raw, const std::string& allowed) {
    require(raw.is_array(), "Labels must be rows");
    for (const auto& value : raw.as_array()) {
      work.tick();
      const auto row = object(value, "learning label");
      require(row.size() == 2 && row.contains(data.id_field) && row.contains("value"),
              "Each label needs an entity ID and value");
      const auto i = index(row.at(data.id_field));
      require(data.splits[i] == allowed && labeled.insert(i).second,
              "Labels must belong only to their declared split with no repeats");
      require(!row.at("value").is_null(), "Labels must not be null");
      data.targets[i] = row.at("value");
    }
  };
  labels(training_labels.at("rows"), "train");
  if (specification.contains("validation_labels"))
    labels(specification.at("validation_labels"), "validation");
  if (specification.contains("test_labels")) labels(specification.at("test_labels"), "test");
  for (std::size_t i = 0; i < data.ids.size(); ++i)
    if (data.splits[i] == "train")
      require(!data.targets[i].is_null(), "Every training entity needs a training label");
}

json::object supervised(Dataset data, const std::string& task, const json::object& args,
                        Work& work) {
  using namespace family_util;
  using namespace numeric;
  require(task == "classification" || task == "regression", "Invalid supervised task");
  const auto configuration = training(args);
  const auto prediction_split =
      choice(args, "prediction_split", "all", {"all", "train", "validation", "test", "inference"});
  const bool standardize = boolean(args, "standardize", true);
  NativeRandom random(args);
  const auto n = data.ids.size(), d = data.features.cols;
  require(data.features.rows == n && data.splits.size() == n && data.targets.size() == n,
          "Invalid learning dataset shape");
  std::vector<std::size_t> train;
  for (std::size_t i = 0; i < n; ++i)
    if (data.splits[i] == "train") train.push_back(i);
  require(!train.empty(), "Training split must not be empty");
  std::vector<ExternalId> classes;
  std::map<ExternalId, std::size_t> class_index;
  if (task == "classification") {
    std::set<ExternalId> labels;
    for (const auto i : train) labels.insert(external_id(data.targets[i]));
    classes.assign(labels.begin(), labels.end());
    for (std::size_t i = 0; i < classes.size(); ++i) class_index[classes[i]] = i;
  }
  const auto outputs = task == "classification" ? classes.size() : 1;
  std::vector<double> mean(d, 0), scale(d, 1);
  if (standardize)
    for (std::size_t c = 0; c < d; ++c) {
      long double sum = 0;
      for (const auto i : train) {
        work.tick();
        sum += data.features(i, c);
      }
      mean[c] = finite(sum / train.size());
      long double variance = 0;
      for (const auto i : train) {
        const long double delta = static_cast<long double>(data.features(i, c)) - mean[c];
        variance += delta * delta;
      }
      scale[c] = finite(std::sqrt(variance / train.size()));
      if (scale[c] == 0) scale[c] = 1;
    }
  Matrix design(n, d + 1, work);
  for (std::size_t i = 0; i < n; ++i) {
    for (std::size_t c = 0; c < d; ++c)
      design(i, c) = finite((static_cast<long double>(data.features(i, c)) - mean[c]) / scale[c]);
    design(i, d) = 1;
  }
  std::vector<double> targets(n, 0);
  for (const auto i : train)
    targets[i] = task == "classification" ? class_index.at(external_id(data.targets[i]))
                                          : float64(data.targets[i], "training target");
  Matrix coefficients(d + 1, outputs, work);
  for (auto& value : coefficients.values) value = random_initial(random);
  Objective objective = [&](const auto& parameters, auto& gradient) {
    long double loss = 0;
    for (const auto i : train) {
      std::vector<double> logits(outputs);
      for (std::size_t k = 0; k < outputs; ++k) {
        long double value = 0;
        for (std::size_t c = 0; c <= d; ++c) {
          work.tick();
          value += static_cast<long double>(design(i, c)) * parameters[c + (d + 1) * k];
        }
        logits[k] = finite(value);
      }
      if (task == "classification") {
        const auto maximum = *std::max_element(logits.begin(), logits.end());
        long double mass = 0;
        for (const auto value : logits) mass += std::exp(static_cast<long double>(value) - maximum);
        loss += (maximum + std::log(mass) - logits[static_cast<std::size_t>(targets[i])]) /
                train.size();
        for (std::size_t k = 0; k < outputs; ++k) {
          const auto residual = (std::exp(static_cast<long double>(logits[k]) - maximum) / mass -
                                 (k == static_cast<std::size_t>(targets[i]))) /
                                train.size();
          for (std::size_t c = 0; c <= d; ++c)
            gradient[c + (d + 1) * k] += finite(design(i, c) * residual);
        }
      } else {
        const long double residual = static_cast<long double>(logits[0]) - targets[i];
        loss += residual * residual / (2 * train.size());
        for (std::size_t c = 0; c <= d; ++c)
          gradient[c] += finite(design(i, c) * residual / train.size());
      }
    }
    for (std::size_t p = 0; p < parameters.size(); ++p) {
      loss += configuration.l2 * static_cast<long double>(parameters[p]) * parameters[p] / 2;
      gradient[p] += configuration.l2 * parameters[p];
    }
    return finite(loss);
  };
  const auto fitted = minimize(coefficients.values, configuration, objective, work);
  coefficients.values = fitted.parameters;
  const auto logits = multiply(design, coefficients, work);
  Matrix probabilities(n, outputs, work);
  std::vector<std::size_t> predicted(n, 0);
  for (std::size_t i = 0; i < n; ++i)
    if (task == "classification") {
      double maximum = logits(i, 0);
      for (std::size_t k = 1; k < outputs; ++k)
        if (logits(i, k) > maximum) {
          maximum = logits(i, k);
          predicted[i] = k;
        }
      long double mass = 0;
      for (std::size_t k = 0; k < outputs; ++k)
        mass += std::exp(static_cast<long double>(logits(i, k)) - maximum);
      for (std::size_t k = 0; k < outputs; ++k)
        probabilities(i, k) =
            finite(std::exp(static_cast<long double>(logits(i, k)) - maximum) / mass);
    }
  json::array predictions, class_values;
  for (const auto& label : classes) class_values.push_back(id_json(label));
  for (std::size_t i = 0; i < n; ++i)
    if (prediction_split == "all" || data.splits[i] == prediction_split) {
      json::object row{{data.id_field, id_json(data.ids[i])}, {"split", data.splits[i]}};
      if (task == "classification") {
        row["prediction"] = id_json(classes[predicted[i]]);
        json::array values;
        for (std::size_t k = 0; k < outputs; ++k) values.push_back(probabilities(i, k));
        row["probabilities"] = values;
      } else
        row["prediction"] = logits(i, 0);
      predictions.push_back(row);
    }
  // These labels were never read by the fitting objective or preprocessing.
  json::object metrics;
  for (const auto* name : {"train", "validation", "test"}) {
    std::size_t count = 0, total = 0, correct = 0;
    long double squared = 0, absolute = 0;
    std::map<ExternalId, std::array<std::size_t, 3>> confusion;
    for (const auto& label : classes) confusion[label] = {0, 0, 0};
    for (std::size_t i = 0; i < n; ++i)
      if (data.splits[i] == name) {
        ++total;
        if (data.targets[i].is_null()) continue;
        ++count;
        if (task == "classification") {
          const auto truth = external_id(data.targets[i]);
          const auto& estimate = classes[predicted[i]];
          if (truth == estimate) {
            ++correct;
            ++confusion[truth][0];
          } else {
            ++confusion[estimate][1];
            ++confusion[truth][2];
          }
        } else {
          const auto truth = float64(data.targets[i], "evaluation target");
          const long double delta = static_cast<long double>(logits(i, 0)) - truth;
          squared += delta * delta;
          absolute += std::abs(delta);
        }
      }
    json::object row{{"entity_count", total}, {"labeled_count", count}};
    if (task == "classification") {
      long double macro = 0;
      for (const auto& [label, values] : confusion) {
        const auto denominator = 2 * values[0] + values[1] + values[2];
        if (denominator) macro += static_cast<long double>(2 * values[0]) / denominator;
      }
      row["accuracy"] =
          count ? json::value(static_cast<double>(correct) / count) : json::value(nullptr);
      row["macro_f1"] =
          count ? json::value(finite(macro / confusion.size())) : json::value(nullptr);
      row["correct_count"] = correct;
      row["macro_f1_class_count"] = confusion.size();
    } else {
      row["mean_squared_error"] =
          count ? json::value(finite(squared / count)) : json::value(nullptr);
      row["mean_absolute_error"] =
          count ? json::value(finite(absolute / count)) : json::value(nullptr);
    }
    metrics[name] = row;
  }
  const auto loss = task == "classification" ? "mean training softmax cross entropy plus l2/2 "
                                               "times squared coefficients (including intercept)"
                                             : "mean training half squared error plus l2/2 times "
                                               "squared coefficients (including intercept)";
  json::object state{{"format", "graphmine-linear-readout-v1"},
                     {"task", task},
                     {"coefficients", matrix(coefficients)},
                     {"classes", class_values},
                     {"feature_mean", array(mean)},
                     {"feature_scale", array(scale)},
                     {"intercept_row", d},
                     {"standardize", standardize},
                     {"preprocessing_fit_split", "train"},
                     {"random_seed", random.seed}};
  auto report = summary(fitted, configuration, loss);
  report["training_entity_count"] = train.size();
  report["label_fit_split"] = "train";
  report["random_seed"] = random.seed;
  work.output(predictions.size() * (1 + outputs) + (d + 1) * outputs + 2 * d +
              fitted.history.size());
  return {{"predictions", predictions},
          {"metrics", metrics},
          {"model_state", state},
          {"training_summary", report}};
}
}  // namespace graphmine::runtime::learning
