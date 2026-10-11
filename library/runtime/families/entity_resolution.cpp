#include <unicode/normalizer2.h>
#include <unicode/uchar.h>
#include <unicode/unistr.h>

#include "pattern_match.hpp"

namespace graphmine::runtime {
namespace {
using namespace family_util;
using Text = std::vector<UChar32>;
Text unicode_text(const std::string& raw, const std::string& normalization, Work& work) {
  work.tick(raw.size());
  require(raw.size() <= INT32_MAX, "Text exceeds ICU length limit");
  auto text = icu::UnicodeString::fromUTF8(icu::StringPiece(raw));
  if (normalization == "nfkc_casefold") {
    UErrorCode status = U_ZERO_ERROR;
    const auto* nfkc = icu::Normalizer2::getNFKCInstance(status);
    require(U_SUCCESS(status), "ICU NFKC initialization failed");
    icu::UnicodeString normalized;
    nfkc->normalize(text, normalized, status);
    require(U_SUCCESS(status), "ICU normalization failed");
    text = std::move(normalized);
  }
  if (normalization != "none") text.foldCase();
  Text result;
  for (std::int32_t i = 0; i < text.length();) {
    const auto code = text.char32At(i);
    result.push_back(code);
    i += U16_LENGTH(code);
  }
  return result;
}
struct Predicate {
  std::string op;
  Exact distance = 0;
  std::vector<std::optional<json::value>> values;
  std::vector<Text> text;
  std::vector<std::set<Text>> tokens;
};
struct Rule {
  std::vector<Predicate> predicates;
  Rule(const json::value& input, const std::vector<json::object>& records, Work& work) {
    const auto spec = object(input, "entity rule");
    fields(spec, {"all"}, {"all"});
    require(spec.at("all").is_array() && !spec.at("all").as_array().empty(),
            "Rule needs a nonempty all array");
    for (const auto& raw : spec.at("all").as_array()) {
      const auto row = object(raw, "entity predicate");
      fields(row, {"field", "operator", "max_distance", "normalization", "optional"},
             {"field", "operator"});
      const auto field = string(row.at("field"), "field");
      require(!field.empty() && field.front() != '.' && field.back() != '.' &&
                  field.find("..") == std::string::npos,
              "Invalid attributes field path");
      Predicate p;
      p.op = choice(row, "operator", "eq",
                    {"eq", "shared_token", "edit_distance", "numeric_difference"});
      const auto normalization =
          choice(row, "normalization", "none", {"none", "casefold", "nfkc_casefold"});
      const auto optional = boolean(row, "optional", false);
      if (p.op == "numeric_difference" || p.op == "edit_distance") {
        require(row.contains("max_distance"), "Distance predicate needs max_distance");
        p.distance = exact_number(row.at("max_distance"), "max_distance");
        require(p.distance >= 0, "max_distance must be nonnegative");
        if (p.op == "edit_distance") uint(row.at("max_distance"), "edit-distance cutoff");
      } else
        require(!row.contains("max_distance"), "max_distance requires a distance predicate");
      require(p.op != "numeric_difference" || normalization == "none",
              "Numeric difference does not accept text normalization");
      for (const auto& record : records) {
        work.tick();
        const auto* value = record_field(record, "attributes." + field);
        p.values.push_back(value ? std::optional<json::value>(*value) : std::nullopt);
        p.text.emplace_back();
        p.tokens.emplace_back();
        if (!value) {
          require(optional, "Record is missing required field " + field);
          continue;
        }
        if (p.op == "numeric_difference") {
          exact_number(*value, field);
          continue;
        }
        if (p.op == "shared_token" || p.op == "edit_distance" || normalization != "none") {
          const auto codepoints = unicode_text(string(*value, field), normalization, work);
          p.text.back() = codepoints;
          if (p.op == "eq") {
            icu::UnicodeString text;
            for (const auto code : codepoints) text.append(code);
            std::string utf8;
            text.toUTF8String(utf8);
            p.values.back() = json::value(utf8);
          }
          if (p.op == "shared_token") {
            Text token;
            for (const auto code : codepoints) {
              const bool space = u_isUWhiteSpace(code) || (code >= 0x1c && code <= 0x1f);
              if (space) {
                if (!token.empty()) {
                  p.tokens.back().insert(token);
                  token.clear();
                }
              } else
                token.push_back(code);
            }
            if (!token.empty()) p.tokens.back().insert(token);
          }
        }
      }
      predicates.push_back(std::move(p));
    }
  }
  bool match(VertexIndex u, VertexIndex v, Work& work) const {
    for (const auto& p : predicates) {
      work.tick();
      if (!p.values[u] || !p.values[v]) return false;
      if (p.op == "eq") {
        if (!typed_equal(*p.values[u], *p.values[v], work)) return false;
      } else if (p.op == "numeric_difference") {
        const Exact difference = exact_number(*p.values[u], "numeric field") -
                                 exact_number(*p.values[v], "numeric field");
        if (abs(difference) > p.distance) return false;
      } else if (p.op == "shared_token") {
        bool common = false;
        for (const auto& token : p.tokens[u]) {
          work.tick();
          if (p.tokens[v].count(token)) {
            common = true;
            break;
          }
        }
        if (!common) return false;
      } else {
        const auto& a = p.text[u];
        const auto& b = p.text[v];
        if (p.distance >= std::max(a.size(), b.size())) continue;
        if (Exact(a.size() > b.size() ? a.size() - b.size() : b.size() - a.size()) > p.distance)
          return false;
        work.tick(b.size() + 1);
        std::vector<std::size_t> previous(b.size() + 1), current(b.size() + 1);
        std::iota(previous.begin(), previous.end(), 0);
        for (std::size_t i = 0; i < a.size(); ++i) {
          current[0] = i + 1;
          for (std::size_t j = 0; j < b.size(); ++j) {
            work.tick();
            current[j + 1] =
                std::min({previous[j + 1] + 1, current[j] + 1, previous[j] + (a[i] != b[j])});
          }
          std::swap(previous, current);
        }
        if (Exact(previous.back()) > p.distance) return false;
      }
    }
    return true;
  }
};
std::vector<Vertices> components(const MiningGraph& adj, Work& work) {
  std::vector<Vertices> result;
  std::vector<bool> seen(adj.size(), false);
  for (VertexIndex v = 0; v < adj.size(); ++v)
    if (!seen[v]) {
      Vertices group{v};
      seen[v] = true;
      for (std::size_t i = 0; i < group.size(); ++i)
        for (const auto u : adj[group[i]]) {
          work.tick();
          if (!seen[u]) {
            seen[u] = true;
            group.push_back(u);
          }
        }
      std::sort(group.begin(), group.end());
      result.push_back(group);
    }
  return result;
}
}  // namespace
json::object entity_resolution(const Graph& graph, const json::object& args, const std::string&,
                               int, Work& work) {
  using namespace family_util;
  fields(args,
         {"task", "blocking_rules", "match_decision_rule", "clustering_policy", "solution_quality"},
         {"task", "blocking_rules"});
  const auto task = choice(args, "task", "blocking", {"blocking", "resolution"}),
             policy = choice(args, "clustering_policy", "connected_components",
                             {"connected_components", "correlation_clustering"}),
             quality = choice(args, "solution_quality", "exact", {"exact", "approximate"});
  require(args.at("blocking_rules").is_array() && !args.at("blocking_rules").as_array().empty(),
          "blocking_rules must be nonempty");
  const auto n = graph.vertex_count();
  std::vector<json::object> records;
  for (const auto& v : graph.canonical().vertices) records.push_back(vertex_record_json(v, work));
  std::vector<Rule> rules;
  std::vector<ExternalId> rule_ids;
  std::set<ExternalId> seen;
  for (const auto& raw : args.at("blocking_rules").as_array()) {
    const auto spec = object(raw, "blocking rule");
    fields(spec, {"id", "all"}, {"id", "all"});
    const auto id = external_id(spec.at("id"));
    require(seen.insert(id).second, "Blocking rule IDs must be unique");
    rule_ids.push_back(id);
    rules.emplace_back(json::object{{"all", spec.at("all")}}, records, work);
  }
  std::optional<Rule> decision;
  const auto raw_decision =
      args.contains("match_decision_rule") ? args.at("match_decision_rule") : json::value(nullptr);
  if (task == "resolution") {
    require(!raw_decision.is_null(), "Resolution requires match_decision_rule");
    decision.emplace(raw_decision, records, work);
  } else
    require(raw_decision.is_null() && policy == "connected_components",
            "Match decisions and clustering apply only to resolution");
  json::array candidates, matches;
  std::map<std::pair<VertexIndex, VertexIndex>, bool> decisions;
  MiningGraph candidate_graph(n), match_graph(n);
  std::uint64_t materialized = 0;
  for (VertexIndex u = 0; u < n; ++u)
    for (VertexIndex v = u + 1; v < n; ++v) {
      work.tick();
      json::array satisfied;
      for (std::size_t r = 0; r < rules.size(); ++r)
        if (rules[r].match(u, v, work)) satisfied.push_back(id_json(rule_ids[r]));
      if (satisfied.empty()) continue;
      candidates.push_back(json::object{{"source", id_json(graph.external_id(u))},
                                        {"target", id_json(graph.external_id(v))},
                                        {"rule_ids", satisfied}});
      candidate_graph[u].push_back(v);
      candidate_graph[v].push_back(u);
      if (decision) {
        const bool matched = decision->match(u, v, work);
        decisions[{u, v}] = matched;
        if (matched) {
          match_graph[u].push_back(v);
          match_graph[v].push_back(u);
        }
        matches.push_back(json::object{{"source", id_json(graph.external_id(u))},
                                       {"target", id_json(graph.external_id(v))},
                                       {"match", matched}});
      }
      materialized += 1 + satisfied.size() + static_cast<bool>(decision);
      work.output(materialized);
    }
  const auto possible = std::uint64_t(n) * (n ? n - 1 : 0) / 2;
  json::object data{
      {"candidate_pairs", candidates},
      {"reduction_ratio", possible ? 1 - static_cast<double>(candidates.size()) / possible : 0},
      {"complete", true}},
      ports{{"candidates", result_port("record_pair_collection", candidates)}};
  if (decision) {
    std::vector<Vertices> groups;
    if (policy == "connected_components")
      groups = components(match_graph, work);
    else
      for (const auto& component : components(candidate_graph, work)) {
        std::size_t best = SIZE_MAX;
        std::vector<std::size_t> selected;
        partitions(component.size(), 1, component.size(), work, [&](const auto& assignment) {
          std::size_t cost = 0;
          for (std::size_t i = 0; i < component.size(); ++i)
            for (std::size_t j = i + 1; j < component.size(); ++j) {
              work.tick();
              const auto it = decisions.find({component[i], component[j]});
              if (it != decisions.end()) cost += ((assignment[i] == assignment[j]) != it->second);
            }
          if (cost < best) {
            best = cost;
            selected = assignment;
          }
        });
        std::map<std::size_t, Vertices> local;
        for (std::size_t i = 0; i < component.size(); ++i)
          local[selected[i]].push_back(component[i]);
        for (auto& [part, vertices] : local) groups.push_back(std::move(vertices));
      }
    std::sort(groups.begin(), groups.end());
    std::vector<std::size_t> cluster(n);
    for (std::size_t c = 0; c < groups.size(); ++c)
      for (auto v : groups[c]) cluster[v] = c;
    std::size_t disagreements = 0;
    for (const auto& [pair, match] : decisions)
      disagreements += ((cluster[pair.first] == cluster[pair.second]) != match);
    json::array assignments;
    for (VertexIndex v = 0; v < n; ++v)
      assignments.push_back(
          json::object{{"vertex", id_json(graph.external_id(v))}, {"cluster", cluster[v]}});
    data["resolved_entity_id"] = assignments;
    data["match_decision"] = matches;
    data["candidate_pair_disagreements"] = disagreements;
    data["clustering_optimal"] = policy == "correlation_clustering";
    ports["clusters"] = result_port("vertex_partition", assignments);
    work.output(materialized + n);
  }
  auto result = output({{"task", task},
                        {"blocking_rules", args.at("blocking_rules")},
                        {"match_decision_rule", raw_decision},
                        {"clustering_policy", policy},
                        {"solution_quality", quality}},
                       data, ports);
  result["diagnostics"] =
      json::object{{"input_edges", "ignored_coreference_hints"},
                   {"noncandidate_pairs", "neutral"},
                   {"missing_optional_field", "predicate_false"},
                   {"normalization", "ICU NFKC followed by full case folding"},
                   {"unicode_library_version", U_ICU_VERSION},
                   {"edit_distance", "unit codepoint Levenshtein"},
                   {"tokenization", "Unicode whitespace split including U+001C..U+001F"}};
  return result;
}
}  // namespace graphmine::runtime
