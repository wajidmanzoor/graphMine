#include "internal.hpp"
#include "record_query.hpp"
#include "representation_cache.hpp"
#include "structured_input.hpp"

namespace graphmine::runtime {
namespace {
bool schema_type(const json::value& value, const std::string& type) {
  if (type == "object") return value.is_object();
  if (type == "array") return value.is_array();
  if (type == "integer") return value.is_int64() || value.is_uint64();
  if (type == "number") return value.is_number();
  if (type == "boolean") return value.is_bool();
  if (type == "string") return value.is_string();
  if (type == "null") return value.is_null();
  throw Failure("invalid_input", "Unknown native schema type");
}
void schema_value(const json::value& value, const json::object& schema, const std::string& path,
                  std::size_t depth = 0) {
  require(depth < 128, "Parameter nesting exceeds the contract limit");
  if (schema.contains("type")) {
    const auto& type = schema.at("type");
    bool matches = false;
    if (type.is_array()) {
      for (const auto& alternative : type.as_array())
        matches |= schema_type(value, string(alternative, "schema type"));
    } else
      matches = schema_type(value, string(type, "schema type"));
    require(matches, path + " has an invalid nested type");
  }
  if (schema.contains("enum")) {
    const auto& values = schema.at("enum").as_array();
    require(std::find(values.begin(), values.end(), value) != values.end(),
            path + " has an unsupported choice");
  }
  if (value.is_object()) {
    const auto& object = value.as_object();
    if (schema.contains("required"))
      for (const auto& key : schema.at("required").as_array())
        require(object.contains(key.as_string()),
                path + " is missing " + std::string(key.as_string()));
    if (schema.contains("properties")) {
      const auto& properties = schema.at("properties").as_object();
      for (const auto& field : object) {
        if (properties.contains(field.key()))
          schema_value(field.value(), properties.at(field.key()).as_object(),
                       path + "." + std::string(field.key()), depth + 1);
        else
          require(!schema.contains("additionalProperties") ||
                      schema.at("additionalProperties").as_bool(),
                  path + " has an unknown field " + std::string(field.key()));
      }
    }
  }
  if (value.is_array()) {
    const auto& array = value.as_array();
    if (schema.contains("minItems"))
      require(array.size() >= uint(schema.at("minItems"), "minItems"),
              path + " has too few entries");
    if (schema.contains("items"))
      for (const auto& item : array)
        schema_value(item, schema.at("items").as_object(), path + "[]", depth + 1);
  }
  if (value.is_string() && schema.contains("minLength"))
    require(value.as_string().size() >= uint(schema.at("minLength"), "minLength"),
            path + " must not be empty");
  if (value.is_number()) {
    const auto number = value.to_number<double>();
    if (schema.contains("minimum"))
      require(number >= schema.at("minimum").to_number<double>(), path + " is below its minimum");
    if (schema.contains("exclusiveMinimum"))
      require(number > schema.at("exclusiveMinimum").to_number<double>(),
              path + " must exceed its minimum");
    if (schema.contains("maximum"))
      require(number <= schema.at("maximum").to_number<double>(), path + " exceeds its maximum");
  }
}
void parameter_value(const json::value& value, const json::object& spec, const std::string& name) {
  if (value.is_null() && spec.at("nullable").as_bool()) return;
  const auto kind = string(spec.at("kind"), "parameter kind");
  const bool valid = kind == "integer"   ? value.is_int64() || value.is_uint64()
                     : kind == "number"  ? value.is_number()
                     : kind == "boolean" ? value.is_bool()
                     : kind == "string"  ? value.is_string()
                     : kind == "array"   ? value.is_array()
                     : kind == "object"  ? value.is_object()
                     : kind == "vertex_id"
                         ? value.is_string() || value.is_int64() || value.is_uint64()
                         : false;
  require(valid, name + " must have type " + kind);
  if (kind == "vertex_id") external_id(value);
  if (value.is_number()) {
    const auto number = value.to_number<double>();
    require(std::isfinite(number), name + " must be finite");
    if (spec.contains("minimum"))
      require(number >= spec.at("minimum").to_number<double>(), name + " is below its minimum");
    if (spec.contains("maximum"))
      require(number <= spec.at("maximum").to_number<double>(), name + " exceeds its maximum");
  }
  if (spec.contains("choices")) {
    const auto& choices = spec.at("choices").as_array();
    require(std::find(choices.begin(), choices.end(), value) != choices.end(),
            name + " has an unsupported choice");
  }
  if (spec.contains("json_schema")) schema_value(value, spec.at("json_schema").as_object(), name);
}
}  // namespace

void validate_parameters(const json::object& card, const json::object& parameters, bool partial) {
  const auto& specs = card.at("parameters").as_object();
  for (const auto& parameter : parameters) {
    require(specs.contains(parameter.key()),
            "Unsupported parameter: " + std::string(parameter.key()));
    parameter_value(parameter.value(), specs.at(parameter.key()).as_object(),
                    std::string(parameter.key()));
  }
  if (!partial)
    for (const auto& spec : specs)
      require(!spec.value().as_object().at("required").as_bool() || parameters.contains(spec.key()),
              "Missing required parameter: " + std::string(spec.key()));
}

json::object inspect_input(const std::string& kind, const json::value& value, Work& work) {
  json::object result{{"input_kind", kind}, {"input_fingerprint", input_fingerprint(value)}};
  if (kind == "graph") {
    const auto graph = cached_graph(value, work);
    result["vertex_count"] = graph->vertex_count();
    result["edge_count"] = graph->edge_count();
  } else if (kind == "graph_collection")
    result["graph_count"] = graph_collection(value, work).size();
  else if (kind == "hypergraph") {
    const HypergraphInput input(value, work);
    result["vertex_count"] = input.ids.size();
    result["hyperedge_count"] = input.edges.size();
  } else if (kind == "feature_vectors") {
    const FeatureInput input(value, work);
    result["vertex_count"] = input.ids.size();
  } else
    throw Failure("invalid_input", "Unknown input kind");
  return result;
}

json::object validate_request(const json::object& request) {
  fields(request, {"command", "operation", "graph", "parameters", "device", "partial_parameters"},
         {"command", "operation"});
  const auto operation = string(request.at("operation"), "operation");
  const auto& card = operation_card(operation);
  const auto parameters = request.contains("parameters")
                              ? object(request.at("parameters"), "parameters")
                              : json::object{};
  validate_parameters(card, parameters, boolean(request, "partial_parameters", false));
  const auto policy = request.contains("device") ? string(request.at("device"), "device") : "auto";
  require(policy == "auto" || policy == "cpu" || policy == "gpu",
          "device must be cpu, gpu or auto");
  json::object result{{"operation", operation},
                      {"parameters", parameters},
                      {"input_kind", card.at("input_kind")},
                      {"validation_scope",
                       "contract_and_literal_input; dependent inputs and algorithm constraints are "
                       "checked at execution"}};
  if (policy == "gpu") {
    bool compiled = false;
    for (const auto& entry : card.at("backends").as_array()) {
      const auto& backend = entry.as_object();
      compiled |= backend.at("device") == "gpu" && backend.at("compiled").as_bool();
    }
    if (!compiled) throw Failure("backend_unavailable", "No compiled GPU profile for " + operation);
  }
  if (request.contains("graph")) {
    Work work;
    const auto kind = string(card.at("input_kind"), "input_kind");
    const auto inspected = inspect_input(kind, request.at("graph"), work);
    result["input_fingerprint"] = inspected.at("input_fingerprint");
    if (kind == "graph") {
      const auto graph = cached_graph(request.at("graph"), work);
      if (policy == "gpu") {
        const auto reason = gpu_support_reason(operation, *graph, parameters);
        if (!reason.empty()) throw Failure("unsupported_input", reason);
        if (!boolean(request, "partial_parameters", false)) {
          bool supported = false;
          std::string rejection;
          for (const auto& entry : card.at("backends").as_array()) {
            const auto& backend = entry.as_object();
            if (backend.at("device") != "gpu" || !backend.at("compiled").as_bool()) continue;
            const auto why = backend_support_reason(operation, string(backend.at("id"), "backend"),
                                                     *graph, parameters, work);
            if (why.empty()) { supported = true; break; }
            rejection = why;
          }
          if (!supported) throw Failure("unsupported_input", rejection.empty() ? "No compatible GPU input profile" : rejection);
        }
      }
      if (!boolean(request, "partial_parameters", false))
        validate_query_parameters(operation, *graph, parameters, work);
    }
  }
  return result;
}
}  // namespace graphmine::runtime
