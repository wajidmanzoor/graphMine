#include "learning.hpp"

namespace graphmine::runtime {
json::object node_embedding(const Graph& graph, const json::object& args, const std::string&, int,
                            Work& work) {
  using namespace family_util;
  using namespace learning;
  using namespace numeric;
  fields(args, {"model", "dimensions", "training_parameters", "random_seed"},
         {"model", "dimensions", "training_parameters"});
  const auto model = choice(args, "model", "line", {"line", "deepwalk", "node2vec"});
  const auto dimension = natural(args, "dimensions", 1, 1), n = graph.vertex_count();
  require(n > 0, "Node embedding requires a nonempty vertex set");
  if (dimension > work.max_candidates / n / 2)
    throw Failure("resource_limit", "Embedding dimensions exceed the candidate budget");
  const auto options = object(args.at("training_parameters"), "training_parameters");
  fields(options,
         {"loss", "optimizer", "epochs", "learning_rate", "l2", "tolerance", "walk_length",
          "walks_per_vertex", "window", "p", "q", "self_loops", "parallel_edges", "direction"});
  choice(options, "loss", "full_softmax", {"full_softmax"});
  const auto loops = choice(options, "self_loops", "reject", {"reject", "drop", "keep"}),
             direction =
                 choice(options, "direction", "preserve", {"preserve", "undirected_projection"});
  choice(options, "parallel_edges", "sum", {"sum"});
  if (model == "line")
    for (const auto* name : {"walk_length", "walks_per_vertex", "window", "p", "q"})
      require(!options.contains(name), std::string(name) + " applies only to walk embeddings");
  if (model != "node2vec")
    require(!options.contains("p") && !options.contains("q"), "p and q require node2vec");
  struct Arc {
    VertexIndex vertex;
    Exact weight;
  };
  std::vector<std::map<VertexIndex, Exact>> adjacency(n);
  for (const auto& edge : graph.canonical().edges) {
    work.tick();
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    require(edge.weight.value_or(1) >= 0, "Embedding weights must be nonnegative");
    if (u == v) {
      require(loops != "reject", "Node embedding profile rejects loops");
      if (loops == "drop") continue;
    }
    const Exact weight(edge.weight.value_or(1));
    adjacency[u][v] += weight;
    if (u != v && (!graph.directed() || direction == "undirected_projection"))
      adjacency[v][u] += weight;
  }
  std::vector<std::vector<Arc>> rows(n);
  for (std::size_t v = 0; v < n; ++v)
    for (const auto& [u, weight] : adjacency[v])
      if (weight > 0) rows[v].push_back({u, weight});
  NativeRandom random(args);
  std::map<std::pair<VertexIndex, VertexIndex>, Exact> pairs;
  std::uint64_t walk_count = 0, walk_events = 0;
  if (model == "line")
    for (VertexIndex v = 0; v < n; ++v)
      for (const auto& arc : rows[v]) pairs[{v, arc.vertex}] += arc.weight;
  else {
    const auto length = natural(options, "walk_length", 20, 1),
               repetitions = natural(options, "walks_per_vertex", 5, 1),
               window = natural(options, "window", 5, 1);
    const Exact p = options.contains("p") ? exact_number(options.at("p"), "p") : Exact(1),
                q = options.contains("q") ? exact_number(options.at("q"), "q") : Exact(1);
    require(p > 0 && q > 0, "Node2vec p and q must be positive");
    for (VertexIndex root = 0; root < n; ++root)
      for (std::uint64_t sample = 0; sample < repetitions; ++sample) {
        work.tick();
        ++walk_count;
        Vertices walk{root};
        for (std::uint64_t step = 0; step < length; ++step) {
          const auto current = walk.back();
          if (rows[current].empty()) break;
          std::vector<Exact> masses;
          for (const auto& arc : rows[current]) {
            Exact mass = arc.weight;
            if (model == "node2vec" && walk.size() > 1) {
              const auto previous = walk[walk.size() - 2];
              if (arc.vertex == previous)
                mass /= p;
              else if (!adjacency[previous].count(arc.vertex) ||
                       adjacency[previous].at(arc.vertex) == 0)
                mass /= q;
            }
            masses.push_back(mass);
          }
          walk.push_back(rows[current][*random.weighted(masses, work)].vertex);
          ++walk_events;
        }
        for (std::size_t i = 0; i < walk.size(); ++i) {
          const auto begin = i > window ? i - window : 0,
                     end = window >= walk.size() - i ? walk.size() : i + window + 1;
          for (std::size_t j = begin; j < end; ++j)
            if (i != j) {
              work.tick();
              pairs[{walk[i], walk[j]}] += 1;
            }
        }
      }
  }
  Exact total = 0;
  for (const auto& entry : pairs) total += entry.second;
  Matrix target(n, n, work);
  if (total > 0)
    for (const auto& [pair, mass] : pairs) {
      target(pair.first, pair.second) = finite((mass / total).convert_to<long double>());
      require(target(pair.first, pair.second) > 0,
              "Positive training mass underflows float64 normalization");
    }
  std::vector<double> source_mass(n, 0);
  for (std::size_t i = 0; i < n; ++i)
    for (std::size_t j = 0; j < n; ++j) source_mass[i] += target(i, j);
  Matrix initial(n, 2 * dimension, work);
  for (auto& value : initial.values) value = random_initial(random);
  const auto configuration = training(options);
  const auto block = n * dimension;
  Objective objective = [&](const auto& parameters, auto& gradient) {
    long double loss = 0;
    for (std::size_t u = 0; u < n; ++u) {
      if (!source_mass[u]) continue;
      std::vector<double> logits(n);
      double maximum = -std::numeric_limits<double>::infinity();
      for (std::size_t v = 0; v < n; ++v) {
        long double score = 0;
        for (std::size_t c = 0; c < dimension; ++c) {
          work.tick();
          score += static_cast<long double>(parameters[u + n * c]) * parameters[block + v + n * c];
        }
        logits[v] = finite(score);
        maximum = std::max(maximum, logits[v]);
      }
      long double denominator = 0;
      for (const auto score : logits)
        denominator += std::exp(static_cast<long double>(score) - maximum);
      const long double log_partition = maximum + std::log(denominator);
      for (std::size_t v = 0; v < n; ++v) {
        loss += target(u, v) * (log_partition - logits[v]);
        const long double residual =
            source_mass[u] * std::exp(static_cast<long double>(logits[v]) - maximum) / denominator -
            target(u, v);
        for (std::size_t c = 0; c < dimension; ++c) {
          gradient[u + n * c] += finite(residual * parameters[block + v + n * c]);
          gradient[block + v + n * c] += finite(residual * parameters[u + n * c]);
        }
      }
    }
    for (std::size_t i = 0; i < parameters.size(); ++i) {
      loss += configuration.l2 * static_cast<long double>(parameters[i]) * parameters[i] / 2;
      gradient[i] += configuration.l2 * parameters[i];
    }
    return finite(loss);
  };
  const auto fitted = minimize(initial.values, configuration, objective, work);
  json::array embeddings, contexts, training_pairs;
  for (VertexIndex v = 0; v < n; ++v) {
    json::array vector, context;
    for (std::size_t c = 0; c < dimension; ++c) {
      vector.push_back(fitted.parameters[v + n * c]);
      context.push_back(fitted.parameters[block + v + n * c]);
    }
    embeddings.push_back(
        json::object{{"vertex", id_json(graph.external_id(v))}, {"values", vector}});
    contexts.push_back(
        json::object{{"vertex", id_json(graph.external_id(v))}, {"values", context}});
  }
  for (const auto& [pair, mass] : pairs)
    training_pairs.push_back(json::object{{"source", id_json(graph.external_id(pair.first))},
                                          {"target", id_json(graph.external_id(pair.second))},
                                          {"mass", fraction_json(mass)}});
  auto report = summary(fitted, configuration,
                        "normalized observed source-context mass times full-softmax negative log "
                        "likelihood plus l2/2 times squared source and context embeddings");
  report["model"] = model;
  report["line_order"] = model == "line" ? json::value(2) : json::value(nullptr);
  report["random_seed"] = random.seed;
  report["training_pairs"] = training_pairs;
  report["walk_count"] = walk_count;
  report["walk_transition_count"] = walk_events;
  report["walk_context_policy"] =
      "symmetric fixed window within directed or undirected sampled walks; repeated occurrences "
      "retain multiplicity";
  report["isolate_policy"] =
      "source has no data loss when absent from contexts; every entity remains a full-softmax "
      "candidate; l2 applies to all vectors";
  report["normalization"] =
      json::object{{"direction", direction}, {"self_loops", loops}, {"parallel_edges", "sum"}};
  work.output(2 * n * dimension + training_pairs.size() + fitted.history.size());
  return output(
      {{"model", model},
       {"dimensions", dimension},
       {"training_parameters", options},
       {"random_seed", random.seed}},
      {{"embeddings", embeddings}, {"context_embeddings", contexts}, {"training_summary", report}},
      {{"embeddings", result_port("vertex_embeddings", embeddings)},
       {"context_embeddings", result_port("vertex_embeddings", contexts)}},
      true, "learned_estimate");
}

json::object knowledge_embedding(const Graph& graph, const json::object& args, const std::string&,
                                 int, Work& work) {
  using namespace family_util;
  using namespace learning;
  using namespace numeric;
  fields(args,
         {"model", "dimensions", "training_triples", "validation_triples", "training_parameters"},
         {"model", "dimensions", "training_triples", "training_parameters"});
  require(graph.directed(), "Knowledge embeddings require directed triples");
  choice(args, "model", "distmult", {"distmult"});
  const auto dimension = natural(args, "dimensions", 1, 1), n = graph.vertex_count();
  require(n > 0, "Knowledge embedding requires entities");
  const auto options = object(args.at("training_parameters"), "training_parameters");
  fields(options, {"loss", "optimizer", "epochs", "learning_rate", "l2", "tolerance",
                   "negative_samples", "random_seed"});
  choice(options, "loss", "logistic_negative_sampling", {"logistic_negative_sampling"});
  const auto negatives = natural(options, "negative_samples", 1, 1);
  NativeRandom random(options);
  const auto configuration = training(options);
  std::map<ExternalId, std::size_t> edge_indices;
  for (std::size_t i = 0; i < graph.edge_count(); ++i) {
    const auto& edge = graph.canonical().edges[i];
    require(edge.type && !edge.type->empty(),
            "Every knowledge edge needs a nonempty relation type");
    edge_indices[edge.id] = i;
  }
  require(args.at("training_triples").is_array() && !args.at("training_triples").as_array().empty(),
          "training_triples must contain edge IDs");
  std::set<ExternalId> selected;
  std::set<std::string> relation_names;
  for (const auto& raw : args.at("training_triples").as_array()) {
    const auto id = external_id(raw);
    require(edge_indices.count(id) && selected.insert(id).second,
            "Training triples need distinct known edge IDs");
    relation_names.insert(*graph.canonical().edges[edge_indices.at(id)].type);
  }
  std::vector<std::string> relations(relation_names.begin(), relation_names.end());
  std::map<std::string, std::size_t> relation_index;
  for (std::size_t i = 0; i < relations.size(); ++i) relation_index[relations[i]] = i;
  using Triple = std::tuple<VertexIndex, std::size_t, VertexIndex>;
  std::set<Triple> positives;
  std::vector<Triple> validation;
  for (const auto& id : selected) {
    const auto& edge = graph.canonical().edges[edge_indices.at(id)];
    positives.emplace(graph.dense_index(edge.source), relation_index.at(*edge.type),
                      graph.dense_index(edge.target));
  }
  const auto raw_validation = args.contains("validation_triples") ? args.at("validation_triples")
                                                                  : json::value(json::array{});
  require(raw_validation.is_array(), "validation_triples must be an array");
  std::set<Triple> validation_seen;
  for (const auto& value : raw_validation.as_array()) {
    const auto row = object(value, "validation triple");
    fields(row, {"source", "type", "target"}, {"source", "type", "target"});
    const auto relation = string(row.at("type"), "relation type");
    require(relation_index.count(relation), "Validation relation must occur in the training split");
    Triple triple{graph.dense_index(external_id(row.at("source"))), relation_index.at(relation),
                  graph.dense_index(external_id(row.at("target")))};
    require(!positives.count(triple) && validation_seen.insert(triple).second,
            "Validation triples must be unique and disjoint from training positives");
    validation.push_back(triple);
  }
  struct Example {
    Triple triple;
    bool positive;
  };
  std::vector<Example> examples;
  for (const auto& triple : positives) {
    examples.push_back({triple, true});
    const auto [u, r, v] = triple;
    std::vector<Triple> corruptions;
    for (VertexIndex candidate = 0; candidate < n; ++candidate) {
      work.tick(2);
      const Triple head{candidate, r, v}, tail{u, r, candidate};
      if (!positives.count(head)) corruptions.push_back(head);
      if (!positives.count(tail)) corruptions.push_back(tail);
    }
    for (std::uint64_t sample = 0; sample < negatives && !corruptions.empty(); ++sample)
      examples.push_back({corruptions[random.uniform(corruptions.size(), work)], false});
  }
  Matrix initial(n + relations.size(), dimension, work);
  for (auto& value : initial.values) value = random_initial(random) * 10;
  const auto stride = n + relations.size();
  auto score = [&](const auto& parameters, const Triple& triple) {
    const auto [u, r, v] = triple;
    long double value = 0;
    for (std::size_t c = 0; c < dimension; ++c) {
      work.tick();
      value += (static_cast<long double>(parameters[u + stride * c]) * parameters[v + stride * c]) *
               parameters[n + r + stride * c];
    }
    return finite(value);
  };
  Objective objective = [&](const auto& parameters, auto& gradient) {
    long double loss = 0;
    for (const auto& example : examples) {
      const auto [u, r, v] = example.triple;
      const auto value = score(parameters, example.triple);
      loss += softplus(example.positive ? -value : value) / examples.size();
      const auto residual = (sigmoid(value) - (example.positive ? 1 : 0)) / examples.size();
      for (std::size_t c = 0; c < dimension; ++c) {
        const auto a = u + stride * c, b = n + r + stride * c, d = v + stride * c;
        gradient[a] += residual * parameters[b] * parameters[d];
        gradient[b] += residual * parameters[a] * parameters[d];
        gradient[d] += residual * parameters[a] * parameters[b];
      }
    }
    for (std::size_t i = 0; i < parameters.size(); ++i) {
      loss += configuration.l2 * static_cast<long double>(parameters[i]) * parameters[i] / 2;
      gradient[i] += configuration.l2 * parameters[i];
    }
    return finite(loss);
  };
  const auto fit = minimize(initial.values, configuration, objective, work);
  json::array entities, relation_rows, training_examples, rankings;
  for (std::size_t i = 0; i < stride; ++i) {
    json::array values;
    for (std::size_t c = 0; c < dimension; ++c) values.push_back(fit.parameters[i + stride * c]);
    if (i < n)
      entities.push_back(
          json::object{{"vertex", id_json(graph.external_id(i))}, {"values", values}});
    else
      relation_rows.push_back(json::object{{"relation", relations[i - n]}, {"values", values}});
  }
  auto triple_row = [&](const Triple& triple) {
    const auto [u, r, v] = triple;
    return json::object{{"source", id_json(graph.external_id(u))},
                        {"type", relations[r]},
                        {"target", id_json(graph.external_id(v))}};
  };
  for (const auto& example : examples) {
    auto row = triple_row(example.triple);
    row["positive"] = example.positive;
    training_examples.push_back(row);
  }
  auto known = positives;
  known.insert(validation.begin(), validation.end());
  long double reciprocal = 0;
  std::size_t hits1 = 0, hits3 = 0, hits10 = 0;
  for (const auto& triple : validation) {
    const auto [u, r, v] = triple;
    const auto target_score = score(fit.parameters, triple);
    for (const auto* side : {"head", "tail"}) {
      std::size_t greater = 0, equal = 0;
      for (VertexIndex candidate = 0; candidate < n; ++candidate) {
        const Triple test =
            std::string(side) == "head" ? Triple{candidate, r, v} : Triple{u, r, candidate};
        if (test == triple || known.count(test)) continue;
        const auto value = score(fit.parameters, test);
        greater += value > target_score;
        equal += value == target_score;
      }
      const auto rank = 1 + greater + 0.5 * equal;
      reciprocal += 1 / rank;
      hits1 += rank <= 1;
      hits3 += rank <= 3;
      hits10 += rank <= 10;
      auto row = triple_row(triple);
      row["side"] = side;
      row["rank"] = rank;
      row["score"] = target_score;
      rankings.push_back(row);
    }
  }
  json::object metrics{
      {"query_count", rankings.size()},
      {"mean_reciprocal_rank",
       rankings.empty() ? json::value(nullptr) : json::value(finite(reciprocal / rankings.size()))},
      {"hits_at_1", rankings.empty() ? json::value(nullptr)
                                     : json::value(static_cast<double>(hits1) / rankings.size())},
      {"hits_at_3", rankings.empty() ? json::value(nullptr)
                                     : json::value(static_cast<double>(hits3) / rankings.size())},
      {"hits_at_10", rankings.empty() ? json::value(nullptr)
                                      : json::value(static_cast<double>(hits10) / rankings.size())},
      {"rankings", rankings}};
  auto report = summary(fit, configuration,
                        "mean logistic loss over training positives and fixed sampled corruptions "
                        "plus l2/2 times all entity and relation squared parameters");
  report["model"] = "distmult";
  report["scoring"] = "sum over dimensions of head * relation * tail";
  report["random_seed"] = random.seed;
  report["training_examples"] = training_examples;
  report["validation_metrics"] = metrics;
  report["negative_filter"] =
      "training positives only; evaluation triples never affect fitting or initialization";
  report["ranking_filter"] =
      "union of training and supplied validation positives, excluding the ranked target; average "
      "tie rank";
  report["isolated_entities"] =
      "transductive random initialization with negative-sampling and regularization updates only";
  work.output(stride * dimension + examples.size() + rankings.size() + fit.history.size());
  return output({{"model", "distmult"},
                 {"dimensions", dimension},
                 {"training_triples", args.at("training_triples")},
                 {"validation_triples", raw_validation},
                 {"training_parameters", options}},
                {{"entity_embeddings", entities},
                 {"relation_embeddings", relation_rows},
                 {"training_summary", report}},
                {{"entities", result_port("vertex_embeddings", entities)},
                 {"relations", result_port("relation_embeddings", relation_rows)}},
                true, "learned_estimate");
}
}  // namespace graphmine::runtime
