#include "internal.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <filesystem>
#include <map>
#include <set>

namespace graphmine::runtime {
namespace {
std::string trim(std::string value) {
  const auto start = value.find_first_not_of(" \t\r\n");
  return start == std::string::npos ? "" : value.substr(start, value.find_last_not_of(" \t\r\n") - start + 1);
}
std::string lower(std::string value) {
  for (auto& c : value) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + 'a' - 'A');
  return value;
}
bool digits(std::string_view value) {
  return !value.empty() && std::all_of(value.begin(), value.end(), [](char c) { return c >= '0' && c <= '9'; });
}
bool canonical_integer(std::string_view value, bool plus) {
  if (!value.empty() && (value[0] == '-' || (plus && value[0] == '+'))) value.remove_prefix(1);
  return digits(value) && (value.size() == 1 || value[0] != '0');
}
std::int64_t integer(std::string_view value, const char* context) {
  if (!value.empty() && value[0] == '+') value.remove_prefix(1);
  std::int64_t result;
  const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
  require(parsed.ec == std::errc{} && parsed.ptr == value.data() + value.size(),
          std::string(context) + " must be an integer within the signed 64-bit native range");
  return result;
}
json::value identifier(const std::string& value, const std::string& id_type) {
  require(!value.empty(), "vertex IDs must not be empty");
  if (id_type == "canonical" && canonical_integer(value, true)) {
    const auto parsed = integer(value, "Vertex ID");
    // Keep lexical IDs such as 001 and -0 rather than changing their identity.
    if (value == std::to_string(parsed) || value == "+" + std::to_string(parsed)) return parsed;
  }
  return json::value(value);
}
json::value scalar(const std::string& value) {
  if (value.empty()) return nullptr;
  if (lower(value) == "true") return true;
  if (lower(value) == "false") return false;
  if (canonical_integer(value, false)) return integer(value, "Attribute value");
  boost::system::error_code error;
  auto parsed = json::parse(value, error);
  if (error || parsed.is_array() || parsed.is_object() ||
      (parsed.is_double() && !std::isfinite(parsed.as_double()))) return json::value(value);
  return parsed;
}
json::value weight(const std::string& value) {
  if (canonical_integer(value, true)) return integer(value, "Weight");
  double result;
  auto view = std::string_view(value);
  if (!view.empty() && view[0] == '+') view.remove_prefix(1);
  const auto parsed = std::from_chars(view.data(), view.data() + view.size(), result);
  require(parsed.ec == std::errc{} && parsed.ptr == view.data() + view.size() && std::isfinite(result),
          "CSV weight must be finite and numeric");
  return result;
}
void consistent(json::object& record, const std::string& name, const json::value& value,
                const char* context) {
  require(!record.contains(name) || record.at(name) == value,
          "Conflicting " + name + " " + context + " for the same vertex ID");
  record[name] = value;
}
}  // namespace

json::object read_graph_file(const json::object& request) {
  fields(request, {"command", "path", "source_column", "target_column", "directed", "id_type", "gpu_device", "max_rows"}, {"command", "path"});
  const auto path = string(request.at("path"), "path");
  const bool edge_list = lower(std::filesystem::path(path).extension().string()) != ".csv";
  require(lower(std::filesystem::path(path).extension().string()) != ".json", "read_graph expects a delimited file; canonical graph JSON can be passed directly to run");
  require(!request.contains("directed") || request.at("directed").is_bool(), "directed must be a boolean");
  const bool directed = request.contains("directed") && request.at("directed").as_bool();
  const auto id_type = request.contains("id_type") ? string(request.at("id_type"), "id_type") : "canonical";
  require(id_type == "canonical" || id_type == "string", "id_type must be canonical or string");
  json::object input{{"command", "read_csv"}, {"path", path}, {"format", edge_list ? "edge_list" : "csv"}};
  for (const auto key : {"gpu_device", "max_rows"}) if (request.contains(key)) input[key] = request.at(key);
  auto loaded = read_csv(input);
  const auto& table = loaded.at("table").as_object();
  std::vector<std::string> columns;
  for (const auto& column : table.at("columns").as_array()) columns.push_back(string(column.as_object().at("name"), "column"));
  auto mapped = [&](const char* parameter, std::initializer_list<const char*> aliases) {
    if (request.contains(parameter)) return string(request.at(parameter), parameter);
    for (const auto alias : aliases) {
      std::string match;
      for (const auto& name : columns) if (lower(trim(name)) == alias) {
        require(match.empty(), "CSV From and To columns are ambiguous; choose their exact names");
        match = name;
      }
      if (!match.empty()) return match;
    }
    return std::string{};
  };
  const auto source = mapped("source_column", {"source", "src", "from"});
  const auto target = mapped("target_column", {"target", "dst", "to"});
  require(!source.empty() && !target.empty(), "Choose the CSV From and To columns, or use source,target headers. For a headerless edge list, use a .txt file.");
  require(source != target && std::find(columns.begin(), columns.end(), source) != columns.end() &&
          std::find(columns.begin(), columns.end(), target) != columns.end(), "Choose two different valid CSV columns (From and To)");
  json::array vertices, edges;
  std::map<ExternalId, std::size_t> positions;
  std::set<std::pair<ExternalId, ExternalId>> pairs;
  bool loops = false, parallel = false;
  for (const auto& raw : table.at("rows").as_array()) {
    std::map<std::string, std::string> row;
    for (const auto& item : raw.as_object()) row[std::string(item.key())] = trim(string(item.value(), "cell"));
    const auto u = identifier(row.at(source), id_type), v = identifier(row.at(target), id_type);
    json::object edge{{"id", row.count("id") && !row.at("id").empty() ? json::value(row.at("id")) : json::value(edges.size() + (edge_list ? 0 : 1))},
                      {"source", u}, {"target", v}};
    for (const auto& side : {std::make_pair("source", u), std::make_pair("target", v)}) {
      const auto inserted = positions.emplace(external_id(side.second), vertices.size());
      if (inserted.second) vertices.push_back(json::object{{"id", side.second}});
      auto& vertex = vertices[inserted.first->second].as_object();
      for (const auto field : {"label", "type"}) {
        const auto key = std::string(side.first) + "_" + field;
        if (row.count(key) && !row.at(key).empty()) consistent(vertex, field, json::value(row.at(key)), "values");
      }
      for (const auto& [name, value] : row) {
        const auto prefix = std::string(side.first) + ".";
        if (name.rfind(prefix, 0) != 0 || value.empty()) continue;
        require(name.size() > prefix.size(), "Vertex attribute name must not be empty");
        if (!vertex.contains("attributes")) vertex["attributes"] = json::object{};
        consistent(vertex.at("attributes").as_object(), name.substr(prefix.size()), scalar(value), "attributes");
      }
    }
    json::object extras;
    for (const auto& [name, value] : row) {
      if (name == source || name == target || name == "id" || name == "source_label" || name == "target_label" ||
          name == "source_type" || name == "target_type" || name.rfind("source.", 0) == 0 || name.rfind("target.", 0) == 0) continue;
      if (name == "weight" && !value.empty()) edge[name] = weight(value);
      else if (name == "timestamp" && !value.empty()) edge[name] = integer(value, "CSV timestamp");
      else if (name == "type" && !value.empty()) edge[name] = value;
      else if (!edge_list) extras[name] = scalar(value);
    }
    if (!extras.empty()) edge["attributes"] = std::move(extras);
    auto pair = std::make_pair(external_id(u), external_id(v));
    loops = loops || pair.first == pair.second;
    if (!directed && pair.second < pair.first) std::swap(pair.first, pair.second);
    if (!pairs.insert(pair).second) parallel = true;
    edges.push_back(std::move(edge));
  }
  auto provenance = loaded.at("provenance").as_object();
  provenance["source_column"] = source;
  provenance["target_column"] = target;
  provenance["id_type"] = id_type;
  provenance["construction"] = "native-canonical-v1";
  provenance["value_policy"] = "trim fields; canonical signed-int64 IDs or explicit string IDs; scalar JSON attributes; finite weights; integer timestamps; preserve parallel records";
  json::object canonical{{"graph", {{"id", std::filesystem::path(path).stem().string()}, {"directed", directed},
                                    {"allows_self_loops", loops}, {"allows_parallel_edges", parallel},
                                    {"attributes", {{"ingestion", provenance}}}}}, {"vertices", vertices}, {"edges", edges}};
  // Use the same graph contract as native algorithm calls, including precision
  // bounds, duplicate IDs and endpoint integrity; never accept a lossy graph.
  parse_graph(canonical);
  return {{"graph", canonical}, {"complete", true}, {"provenance", provenance}};
}
}  // namespace graphmine::runtime
