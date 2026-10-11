#include <algorithm>
#include <charconv>
#include <map>
#include <regex>
#include <set>

#include "exact_number.hpp"

namespace graphmine::runtime {
namespace {
struct Table {
  std::set<std::string> columns;
  json::array rows;
};
using Row = std::map<std::string, const json::object*>;
using Schemas = std::map<std::string, const Table*>;

std::string option(const json::object& spec, const char* name,
                   std::initializer_list<std::string_view> choices) {
  require(spec.contains(name), std::string("Missing projection field: ") + name);
  auto value = string(spec.at(name), name);
  require(std::find(choices.begin(), choices.end(), value) != choices.end(),
          std::string("Unsupported ") + name);
  return value;
}
std::int64_t integer(const json::value& value, const std::string& context) {
  if (value.is_int64()) return value.as_int64();
  if (value.is_uint64() && value.as_uint64() <= INT64_MAX)
    return static_cast<std::int64_t>(value.as_uint64());
  throw Failure("invalid_input", context + " must be a signed 64-bit integer");
}
std::pair<std::string, std::string> field(const std::string& name, const Schemas& schemas) {
  const auto dot = name.find('.');
  require(dot != std::string::npos, "Fields must use alias.column names");
  const auto alias = name.substr(0, dot), column = name.substr(dot + 1);
  require(schemas.count(alias) && schemas.at(alias)->columns.count(column),
          "Unknown projection field: " + name);
  return {alias, column};
}
json::value cell(const Row& row, const std::string& name, const Schemas& schemas) {
  auto [alias, column] = field(name, schemas);
  const auto* record = row.at(alias);
  if (!record) return nullptr;
  return record->at(column);
}
void validate_mapping(const json::object& spec, const Schemas& schemas) {
  fields(spec, {"field", "type", "meaning"}, {"field", "type"});
  field(string(spec.at("field"), "field"), schemas);
  option(spec, "type", {"string", "integer", "number", "boolean"});
}
json::value convert(const json::object& spec, const Row& row, const Schemas& schemas,
                    bool nullable = true) {
  auto value = cell(row, string(spec.at("field"), "field"), schemas);
  const auto type = string(spec.at("type"), "type");
  if (value.is_null() || value.as_string().empty()) {
    require(nullable, "Required projection value is missing: " + string(spec.at("field"), "field"));
    return nullptr;
  }
  const auto text = string(value, "table cell");
  if (type == "string") return value;
  if (type == "boolean") {
    require(text == "true" || text == "false", "Boolean cells must be true or false");
    return text == "true";
  }
  if (type == "integer") {
    std::int64_t parsed;
    const auto result = std::from_chars(text.data(), text.data() + text.size(), parsed);
    require(result.ec == std::errc{} && result.ptr == text.data() + text.size(),
            "Integer conversion requires a signed 64-bit decimal cell");
    return parsed;
  }
  double parsed;
  const auto result = std::from_chars(text.data(), text.data() + text.size(), parsed);
  require(
      result.ec == std::errc{} && result.ptr == text.data() + text.size() && std::isfinite(parsed),
      "Number conversion requires a finite binary64 cell");
  return parsed;
}
json::object attributes(const json::object& specs, const Row& row, const Schemas& schemas) {
  json::object output;
  for (const auto& spec : specs)
    output[spec.key()] = convert(spec.value().as_object(), row, schemas);
  return output;
}
void validate_attributes(const json::object& specs, const Schemas& schemas) {
  for (const auto& item : specs) {
    require(!item.key().empty(), "Attribute names must be nonempty");
    validate_mapping(object(item.value(), "attribute mapping"), schemas);
  }
}
json::object mapped_attributes(const json::object& spec) {
  return spec.contains("attributes") ? object(spec.at("attributes"), "attributes") : json::object{};
}
}  // namespace

json::object project_tables(const json::object& request) {
  fields(request, {"command", "tables", "projection", "gpu_device", "max_rows"},
         {"command", "tables", "projection"});
  const auto sources = object(request.at("tables"), "tables");
  require(!sources.empty() && sources.size() <= 8, "Projection requires one to eight tables");
  const auto maximum =
      request.contains("max_rows") ? uint(request.at("max_rows"), "max_rows") : 100000;
  require(maximum > 0 && maximum <= 1000000, "max_rows must be between 1 and 1,000,000");
  Work work;
  work.max_candidates = 50000000;
  std::map<std::string, Table> tables;
  json::object provenance;
  bool files_only = true;
  for (const auto& item : sources) {
    const auto alias = std::string(item.key());
    require(std::regex_match(alias, std::regex("[A-Za-z][A-Za-z0-9_]{0,63}")),
            "Invalid table alias");
    auto input = object(item.value(), "table source");
    fields(input, {"path", "data"});
    require(input.size() == 1, "Each table requires exactly one path or inline data object");
    json::object table;
    if (input.contains("path")) {
      json::object load{{"command", "read_csv"}, {"path", input.at("path")}, {"max_rows", maximum}};
      if (request.contains("gpu_device")) load["gpu_device"] = request.at("gpu_device");
      const auto loaded = read_csv(load);
      table = loaded.at("table").as_object();
      provenance[alias] = loaded.at("provenance");
    } else {
      files_only = false;
      table = object(input.at("data"), "inline table");
      provenance[alias] =
          json::object{{"reader", "inline-table"}, {"input_sha256", input_fingerprint(table)}};
    }
    fields(table, {"columns", "rows"}, {"columns", "rows"});
    require(table.at("columns").is_array() && table.at("rows").is_array(),
            "Tables need columns and rows arrays");
    auto& target = tables[alias];
    for (const auto& raw : table.at("columns").as_array()) {
      const auto name = raw.is_string() ? string(raw, "column")
                                        : string(object(raw, "column").at("name"), "column");
      require(!name.empty() && target.columns.insert(name).second,
              "Table columns must be nonempty and unique");
    }
    require(!target.columns.empty() && target.columns.size() <= 256, "Table column limit is 256");
    target.rows = table.at("rows").as_array();
    if (target.rows.size() > maximum) throw Failure("resource_limit", "Table row limit exceeded");
    for (const auto& row : target.rows) {
      work.tick();
      const auto record = object(row, "table row");
      require(record.size() == target.columns.size(),
              "Each table row must contain exactly its declared columns");
      for (const auto& column : target.columns)
        require(record.contains(column) && record.at(column).is_string(),
                "Table cells must be text with explicit projection types");
    }
  }
  const auto spec = object(request.at("projection"), "projection");
  fields(spec,
         {"version", "id", "task", "edge_table", "joins", "source", "target", "directed", "weight",
          "timestamp", "time_window", "edge_attributes", "duplicates"},
         {"version", "id", "task", "edge_table", "source", "target", "directed", "duplicates"});
  require(uint(spec.at("version"), "version") == 1, "Unsupported projection version");
  const auto task =
      option(spec, "task", {"topology", "shortest_paths", "spanning_tree", "max_flow", "ranking"});
  const auto duplicate =
      option(spec, "duplicates", {"preserve", "reject", "sum", "min", "max", "count"});
  const auto main = string(spec.at("edge_table"), "edge_table");
  require(tables.count(main), "Unknown edge table");
  const bool directed = boolean(spec, "directed", false);
  Schemas schemas{{main, &tables.at(main)}};
  std::vector<Row> rows;
  for (const auto& row : tables.at(main).rows) rows.push_back({{main, &row.as_object()}});
  json::array join_counts;
  if (spec.contains("joins")) {
    require(spec.at("joins").is_array() && spec.at("joins").as_array().size() <= 8,
            "At most eight joins are allowed");
    for (const auto& raw : spec.at("joins").as_array()) {
      const auto join = object(raw, "join");
      fields(join, {"table", "alias", "left", "right", "kind", "cardinality"},
             {"table", "alias", "left", "right", "kind", "cardinality"});
      const auto table = string(join.at("table"), "table"),
                 alias = string(join.at("alias"), "alias");
      require(tables.count(table) && !schemas.count(alias) &&
                  std::regex_match(alias, std::regex("[A-Za-z][A-Za-z0-9_]{0,63}")),
              "Join needs a known table and unused alias");
      const auto left = string(join.at("left"), "left"), right = string(join.at("right"), "right");
      field(left, schemas);
      require(tables.at(table).columns.count(right), "Unknown join column: " + right);
      option(join, "cardinality", {"many_to_one"});
      const auto kind = option(join, "kind", {"inner", "left", "required"});
      std::map<std::string, const json::object*> index;
      for (const auto& record : tables.at(table).rows) {
        work.tick();
        const auto key = string(record.as_object().at(right), "join key");
        if (!key.empty())
          require(index.emplace(key, &record.as_object()).second,
                  "Join cardinality violated: duplicate right key");
      }
      std::vector<Row> joined;
      std::size_t unmatched = 0;
      for (auto& row : rows) {
        work.tick();
        const auto value = cell(row, left, schemas);
        const auto found = value.is_null() ? index.end() : index.find(string(value, "join key"));
        if (found == index.end()) {
          ++unmatched;
          require(kind != "required", "Required join has an unmatched key");
          if (kind == "inner") continue;
        }
        row[alias] = found == index.end() ? nullptr : found->second;
        joined.push_back(std::move(row));
      }
      rows = std::move(joined);
      schemas[alias] = &tables.at(table);
      join_counts.push_back(
          json::object{{"alias", alias}, {"unmatched", unmatched}, {"retained_rows", rows.size()}});
    }
  }
  for (const auto side : {"source", "target"}) {
    const auto mapping = object(spec.at(side), side);
    fields(mapping, {"field", "type", "attributes"}, {"field", "type"});
    option(mapping, "type", {"string", "integer"});
    auto identifier = mapping;
    identifier.erase("attributes");
    validate_mapping(identifier, schemas);
    validate_attributes(mapped_attributes(mapping), schemas);
  }
  const auto edge_attributes = spec.contains("edge_attributes")
                                   ? object(spec.at("edge_attributes"), "edge_attributes")
                                   : json::object{};
  validate_attributes(edge_attributes, schemas);
  if (spec.contains("weight")) {
    const auto weight = object(spec.at("weight"), "weight");
    validate_mapping(weight, schemas);
    option(weight, "type", {"integer", "number"});
    const auto meaning = option(weight, "meaning", {"cost", "capacity", "strength", "probability"});
    require(task != "shortest_paths" && task != "spanning_tree" || meaning == "cost",
            "Path and tree tasks require cost weights");
    require(task != "max_flow" || meaning == "capacity", "Flow tasks require capacity weights");
    require(task != "ranking" || meaning == "strength" || meaning == "probability",
            "Ranking tasks require strength or probability weights");
    require(duplicate != "count",
            "Count aggregation creates weights and cannot also map a weight column");
  } else {
    require(task == "topology" || (task == "ranking" && duplicate == "count"),
            "This task requires an explicit weight mapping");
    require(duplicate != "sum" && duplicate != "min" && duplicate != "max",
            "Weighted aggregation requires a weight mapping");
  }
  if (spec.contains("timestamp")) {
    const auto timestamp = object(spec.at("timestamp"), "timestamp");
    validate_mapping(timestamp, schemas);
    option(timestamp, "type", {"integer"});
  }
  std::optional<std::int64_t> start, end;
  if (spec.contains("time_window")) {
    require(spec.contains("timestamp"), "Time windows require a timestamp mapping");
    const auto window = object(spec.at("time_window"), "time_window");
    fields(window, {"start", "end"}, {"start", "end"});
    start = integer(window.at("start"), "start");
    end = integer(window.at("end"), "end");
    require(*start < *end, "Time window must have start < end");
  }
  json::array vertices, edges;
  std::map<ExternalId, std::size_t> vertex_index;
  std::map<std::string, std::size_t> edge_index;
  std::vector<Exact> aggregated;
  std::vector<std::uint64_t> counts;
  std::size_t outside_window = 0;
  bool loops = false, parallel = false;
  for (const auto& row : rows) {
    work.tick();
    json::value timestamp;
    if (spec.contains("timestamp"))
      timestamp = convert(spec.at("timestamp").as_object(), row, schemas, false);
    if (start &&
        (integer(timestamp, "timestamp") < *start || integer(timestamp, "timestamp") >= *end)) {
      ++outside_window;
      continue;
    }
    json::object edge{{"id", edges.size()}};
    for (const auto side : {"source", "target"}) {
      const auto mapping = spec.at(side).as_object();
      const auto id = convert(mapping, row, schemas, false);
      const auto attrs = attributes(mapped_attributes(mapping), row, schemas);
      edge[side] = id;
      const auto [position, added] = vertex_index.emplace(external_id(id), vertices.size());
      if (added)
        vertices.push_back(json::object{{"id", id}, {"attributes", attrs}});
      else {
        auto& known = vertices[position->second].as_object().at("attributes").as_object();
        for (const auto& attribute : attrs) {
          require(
              !known.contains(attribute.key()) || known.at(attribute.key()) == attribute.value(),
              "Conflicting projected attributes for the same typed vertex ID");
          known[attribute.key()] = attribute.value();
        }
      }
    }
    if (spec.contains("timestamp")) edge["timestamp"] = timestamp;
    const auto attrs = attributes(edge_attributes, row, schemas);
    edge["attributes"] = attrs;
    Exact weight = 1;
    if (spec.contains("weight")) {
      const auto mapped = convert(spec.at("weight").as_object(), row, schemas, false);
      edge["weight"] = mapped;
      weight = exact_number(mapped, "weight");
      const auto meaning = string(spec.at("weight").as_object().at("meaning"), "meaning");
      require(meaning == "cost" || weight >= 0,
              "Capacity, strength, and probability weights must be nonnegative");
      require(meaning != "probability" || weight <= 1,
              "Probability weights must be between zero and one");
    }
    auto u = external_id(edge.at("source")), v = external_id(edge.at("target"));
    loops = loops || u == v;
    if (!directed && v < u) std::swap(u, v);
    const auto key = json::serialize(json::array{id_json(u), id_json(v), timestamp});
    const auto [position, added] = edge_index.emplace(key, edges.size());
    if (duplicate == "preserve" || added) {
      parallel = parallel || !added;
      edges.push_back(std::move(edge));
      aggregated.push_back(weight);
      counts.push_back(1);
    } else {
      require(duplicate != "reject", "Duplicate edge rejected by projection policy");
      const auto index = position->second;
      require(edges[index].as_object().at("attributes") == attrs,
              "Cannot aggregate duplicate edges with conflicting attributes");
      ++counts[index];
      if (duplicate == "sum") aggregated[index] += weight;
      if (duplicate == "min") aggregated[index] = std::min(aggregated[index], weight);
      if (duplicate == "max") aggregated[index] = std::max(aggregated[index], weight);
    }
  }
  if (duplicate != "preserve" && duplicate != "reject") {
    for (std::size_t i = 0; i < edges.size(); ++i) {
      const auto exact = duplicate == "count" ? Exact(counts[i]) : aggregated[i];
      const auto display = display_number(exact);
      require((display.is_int64() || display.is_uint64() || display.is_double()) &&
                  exact_number(display, "aggregate") == exact,
              "Aggregated weight is not exactly representable; choose a different numeric scale");
      edges[i].as_object()["weight"] = display;
      if (spec.contains("weight") &&
          string(spec.at("weight").as_object().at("meaning"), "meaning") == "probability")
        require(exact <= 1, "Aggregated probability exceeds one");
    }
  }
  // Different event times remain parallel graph edges even when their groups
  // were individually aggregated. Graph semantics describe the final records.
  std::set<std::pair<ExternalId, ExternalId>> pairs;
  for (const auto& raw : edges) {
    const auto& edge = raw.as_object();
    auto u = external_id(edge.at("source")), v = external_id(edge.at("target"));
    if (!directed && v < u) std::swap(u, v);
    parallel = parallel || !pairs.emplace(u, v).second;
  }
  json::object record{
      {"profile", "native-table-projection-v1"},
      {"reader", files_only ? "libcudf" : "inline-table-or-mixed"},
      {"implementation_language", "c++/cuda"},
      {"python_runtime_required", false},
      {"sources", provenance},
      {"projection", spec},
      {"projection_sha256", input_fingerprint(spec)},
      {"source_rows", tables.at(main).rows.size()},
      {"joins", join_counts},
      {"outside_time_window", outside_window},
      {"retained_rows", rows.size() - outside_window},
      {"edge_count", edges.size()},
      {"time_window_semantics", "start_inclusive_end_exclusive"},
      {"join_key_semantics", "exact text; empty keys do not match; many-to-one only"},
      {"numeric_semantics",
       "explicit signed-int64 or binary64 conversion; exact aggregation of admitted values; "
       "unrepresentable sums rejected"}};
  auto id = string(spec.at("id"), "id");
  require(!id.empty(), "Projected graph needs an ID");
  json::object graph{{"graph",
                      {{"id", id},
                       {"directed", directed},
                       {"allows_self_loops", loops},
                       {"allows_parallel_edges", parallel},
                       {"attributes", {{"projection", record}}}}},
                     {"vertices", vertices},
                     {"edges", edges}};
  parse_graph(graph);
  return {{"graph", graph},
          {"complete", true},
          {"provenance", record},
          {"implementation_sha256", catalog().at("implementation_sha256")}};
}
}  // namespace graphmine::runtime
