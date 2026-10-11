#include "learning.hpp"

namespace graphmine::runtime {
namespace {
using namespace family_util;
using namespace learning;
json::object optimizer_parameters(const json::object& model) {
  json::object result;
  for (const auto* field : {"optimizer", "epochs", "learning_rate", "l2", "tolerance",
                            "standardize", "prediction_split", "random_seed"})
    if (model.contains(field)) result[field] = model.at(field);
  if (!result.contains("random_seed")) result["random_seed"] = 0;
  return result;
}
json::object model_parameters(const json::value& input, bool graph_level) {
  const auto result = object(input, "model_definition");
  fields(result,
         graph_level
             ? std::initializer_list<std::string_view>{"architecture", "layers", "direction",
                                                       "self_loops", "parallel_edges", "optimizer",
                                                       "epochs", "learning_rate", "l2", "tolerance",
                                                       "standardize", "prediction_split",
                                                       "random_seed", "feature_source",
                                                       "feature_key", "readout"}
             : std::initializer_list<std::string_view>{"architecture", "layers", "direction",
                                                       "self_loops", "parallel_edges", "optimizer",
                                                       "epochs", "learning_rate", "l2", "tolerance",
                                                       "standardize", "prediction_split",
                                                       "random_seed"},
         {"architecture"});
  choice(result, "architecture", graph_level ? "mean_graph_convolution" : "sgc",
         graph_level ? std::initializer_list<std::string_view>{"mean_graph_convolution"}
                     : std::initializer_list<std::string_view>{"sgc"});
  choice(result, "self_loops", "replace_with_single_self_message",
         {"replace_with_single_self_message"});
  choice(result, "parallel_edges", "collapse", {"collapse"});
  natural(result, "layers", 2, 1);
  return result;
}
json::object result(const json::object& parameters, json::object learned, const char* type) {
  auto output =
      family_util::output(parameters, learned,
                          {{"predictions", result_port(type, learned.at("predictions"))},
                           {"model", result_port("model_state", learned.at("model_state"))},
                           {"metrics", result_port("learning_metrics", learned.at("metrics"))}},
                          true, "learned_estimate");
  output["diagnostics"] = json::object{
      {"label_leakage_policy",
       "Only training labels enter the fitting objective; evaluation labels are read after "
       "fitting"},
      {"topology_feature_policy",
       "transductive; unlabeled features and declared incidence may be used"},
      {"normalization", "one self message; collapsed parallel edges; mean neighbor propagation"}};
  return output;
}
}  // namespace
json::object node_learning(const Graph& graph, const json::object& args, const std::string&, int,
                           Work& work) {
  using namespace family_util;
  using namespace learning;
  fields(args, {"task", "vertex_features", "training_labels", "split", "model_definition"},
         {"task", "vertex_features", "training_labels", "split", "model_definition"});
  const auto task = choice(args, "task", "classification", {"classification", "regression"});
  const auto model = model_parameters(args.at("model_definition"), false);
  const auto features = object(args.at("vertex_features"), "vertex_features");
  fields(features, {"rows"}, {"rows"});
  Dataset data;
  for (const auto& v : graph.canonical().vertices) data.ids.push_back(v.id);
  data.features =
      feature_rows(vertex_values(graph, features.at("rows"), "vertex_features.rows"), work);
  split(data, object(args.at("split"), "split"),
        object(args.at("training_labels"), "training_labels"), work);
  const auto layers = natural(model, "layers", 2, 1);
  const auto direction =
      choice(model, "direction", "incoming", {"incoming", "outgoing", "undirected_projection"});
  data.features = propagate(graph, std::move(data.features), layers, direction, work);
  auto learned = supervised(std::move(data), task, optimizer_parameters(model), work);
  learned.at("model_state").as_object()["graph_model"] = json::object{
      {"architecture", "sgc"},        {"layers", layers},
      {"direction", direction},       {"self_loops", "replace_with_single_self_message"},
      {"parallel_edges", "collapse"}, {"edge_weights", "ignored"}};
  return result(args, learned, "vertex_predictions");
}

json::object graph_learning(const json::value& input, const json::object& args, Work& work) {
  using namespace family_util;
  using namespace learning;
  fields(args, {"task", "graph_labels", "split", "model_definition"},
         {"task", "graph_labels", "split", "model_definition"});
  const auto task = choice(args, "task", "classification", {"classification", "regression"});
  const auto model = model_parameters(args.at("model_definition"), true);
  const auto graphs = graph_collection(input, work);
  require(!graphs.empty(), "Graph learning requires a nonempty collection");
  const auto layers = natural(model, "layers", 2, 1);
  const auto direction =
      choice(model, "direction", "incoming", {"incoming", "outgoing", "undirected_projection"});
  const auto source = choice(model, "feature_source", "structural", {"structural", "attributes"}),
             readout = choice(model, "readout", "mean", {"sum", "mean"});
  const auto key =
      model.contains("feature_key") ? string(model.at("feature_key"), "feature_key") : "features";
  require(!key.empty(), "feature_key must not be empty");
  Dataset data;
  data.id_field = "graph";
  std::vector<json::value> pooled;
  std::optional<std::size_t> dimension =
      source == "structural" ? std::optional<std::size_t>(3) : std::nullopt;
  // Determine one shared attribute width before assigning empty-graph zeros.
  if (source == "attributes")
    for (const auto& graph : graphs)
      for (const auto& vertex : graph.canonical().vertices) {
        const auto record = vertex_record_json(vertex, work);
        const auto* value = record_field(record, "attributes." + key);
        require(value && value->is_array() && !value->as_array().empty(),
                "Every vertex needs the selected feature array");
        if (!dimension) dimension = value->as_array().size();
        require(value->as_array().size() == *dimension,
                "Feature dimension must agree across graphs");
      }
  require(dimension.has_value(),
          "Attribute feature dimension cannot be inferred from only empty graphs");
  for (const auto& graph : graphs) {
    data.ids.emplace_back(graph.canonical().graph.id);
    numeric::Matrix features(graph.vertex_count(), *dimension, work);
    if (source == "structural") {
      for (std::size_t v = 0; v < features.rows; ++v) features(v, 0) = 1;
      for (const auto& edge : edges(graph, false, work, false, false)) {
        ++features(edge.u, 2);
        ++features(edge.v, 1);
        if (!graph.directed()) {
          ++features(edge.v, 2);
          ++features(edge.u, 1);
        }
      }
    } else
      for (std::size_t v = 0; v < features.rows; ++v) {
        const auto record = vertex_record_json(graph.canonical().vertices[v], work);
        const auto* value = record_field(record, "attributes." + key);
        for (std::size_t c = 0; c < *dimension; ++c)
          features(v, c) = numeric::float64(value->as_array()[c], "feature");
      }
    features = propagate(graph, std::move(features), layers, direction, work);
    json::array row;
    for (std::size_t c = 0; c < *dimension; ++c) {
      long double sum = 0;
      for (std::size_t v = 0; v < features.rows; ++v) {
        work.tick();
        sum += features(v, c);
      }
      if (readout == "mean" && features.rows) sum /= features.rows;
      row.push_back(numeric::finite(sum));
    }
    pooled.push_back(row);
  }
  data.features = feature_rows(pooled, work);
  split(data, object(args.at("split"), "split"), object(args.at("graph_labels"), "graph_labels"),
        work);
  auto learned = supervised(std::move(data), task, optimizer_parameters(model), work);
  learned.at("model_state").as_object()["graph_model"] = json::object{
      {"architecture", "mean_graph_convolution"},
      {"layers", layers},
      {"direction", direction},
      {"feature_source", source},
      {"feature_key", key},
      {"readout", readout},
      {"empty_graph", "zero pooled vector"},
      {"structural_feature_order", json::array{"constant_one", "in_degree", "out_degree"}},
      {"edge_weights", "ignored"}};
  auto output = result(args, learned, "graph_predictions");
  output.at("diagnostics").as_object()["topology_feature_policy"] =
      "each graph processed independently; no cross-graph edges";
  return output;
}

json::object hypergraph_learning(const json::value& input, const json::object& args, Work& work) {
  using namespace family_util;
  using namespace learning;
  fields(args,
         {"task", "feature_key", "target_key", "split_key", "model", "seed", "model_parameters"},
         {"model"});
  choice(args, "model", "hgnn-linear-v1", {"hgnn-linear-v1"});
  const auto task = choice(args, "task", "classification", {"classification", "regression"});
  const HypergraphInput graph(input, work);
  auto key = [&](const char* field, const char* fallback) {
    const auto value = args.contains(field) ? string(args.at(field), field) : std::string(fallback);
    require(!value.empty(), std::string(field) + " must not be empty");
    return value;
  };
  const auto feature_key = key("feature_key", "features"), target_key = key("target_key", "target"),
             split_key = key("split_key", "split");
  require(feature_key != target_key && feature_key != split_key && target_key != split_key,
          "Feature, target and split keys must be distinct");
  const auto model = args.contains("model_parameters")
                         ? object(args.at("model_parameters"), "model_parameters")
                         : json::object{};
  fields(model, {"layers", "optimizer", "epochs", "learning_rate", "l2", "tolerance", "standardize",
                 "prediction_split"});
  const auto layers = natural(model, "layers", 1, 1);
  Dataset data;
  data.ids = graph.ids;
  std::vector<json::value> features;
  for (const auto& raw : graph.vertex_records) {
    const auto& record = raw.as_object();
    const auto* value = record_field(record, "attributes." + feature_key);
    require(value, "Missing hypergraph feature field");
    features.push_back(*value);
    const auto* label = record_field(record, "attributes." + target_key);
    const auto* split_value = record_field(record, "attributes." + split_key);
    require(split_value, "Missing hypergraph split field");
    const auto split_name = string(*split_value, "split");
    require(split_name == "train" || split_name == "validation" || split_name == "test" ||
                split_name == "inference",
            "Unknown hypergraph split");
    data.splits.push_back(split_name);
    data.targets.push_back(label ? *label : json::value(nullptr));
    if (split_name == "train")
      require(label && !label->is_null(), "Training vertex needs a target");
  }
  data.features = feature_rows(features, work);
  std::vector<long double> degrees(graph.ids.size(), 0);
  for (const auto& edge : graph.edges) {
    const auto weight = numeric::finite(edge.weight.convert_to<long double>());
    for (const auto v : edge.vertices) degrees[v] += weight;
  }
  for (std::size_t layer = 0; layer < layers; ++layer) {
    numeric::Matrix next(data.features.rows, data.features.cols, work);
    for (const auto& edge : graph.edges) {
      const auto weight = numeric::finite(edge.weight.convert_to<long double>());
      if (!weight) continue;
      for (std::size_t c = 0; c < data.features.cols; ++c) {
        long double mean = 0;
        for (const auto v : edge.vertices) {
          work.tick();
          mean += data.features(v, c);
        }
        mean /= edge.vertices.size();
        for (const auto v : edge.vertices) {
          work.tick();
          next(v, c) =
              numeric::finite(static_cast<long double>(next(v, c)) + weight / degrees[v] * mean);
        }
      }
    }
    for (std::size_t v = 0; v < degrees.size(); ++v)
      if (degrees[v] == 0)
        for (std::size_t c = 0; c < next.cols; ++c) next(v, c) = data.features(v, c);
    data.features = std::move(next);
  }
  auto optimizer = optimizer_parameters(model);
  const auto seed = args.contains("seed") ? args.at("seed") : json::value(0);
  require(seed.is_int64() || seed.is_uint64(), "seed must be an integer");
  optimizer["random_seed"] = seed;
  auto learned = supervised(std::move(data), task, optimizer, work);
  learned.at("model_state").as_object()["graph_model"] = json::object{
      {"architecture", "hgnn-linear-v1"},
      {"layers", layers},
      {"propagation", "D_vertex^-1 H W D_edge^-1 H^T X; isolates retain their own features"},
      {"incidence_policy", "original incidence sets and weights, no pairwise graph projection"},
      {"feature_key", feature_key},
      {"target_key", target_key},
      {"split_key", split_key}};
  learned["model_artifact"] = learned.at("model_state");
  learned["split_metrics"] = learned.at("metrics");
  auto parameters = args;
  parameters["task"] = task;
  parameters["feature_key"] = feature_key;
  parameters["target_key"] = target_key;
  parameters["split_key"] = split_key;
  parameters["seed"] = seed;
  parameters["model_parameters"] = model;
  auto output = result(parameters, learned, "vertex_predictions");
  output.at("diagnostics").as_object()["normalization"] =
      "weighted hyperedge means, then vertex incidence means; isolates retain features";
  return output;
}
}  // namespace graphmine::runtime
