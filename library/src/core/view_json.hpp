#pragma once
#include <boost/json.hpp>
#include <algorithm>
#include <stdexcept>
#include "graphmine/graph.hpp"
namespace graphmine::view_json {
namespace json = boost::json;
inline void require(bool condition, const std::string& message) {
  if (!condition) throw std::invalid_argument(message);
}
json::value strict_json(std::string_view);
inline json::object object(const json::value& value, const std::string& context) {
  require(value.is_object(), context + " must be an object");
  return value.as_object();
}
inline void fields(const json::object& value, std::initializer_list<std::string_view> allowed,
                   std::initializer_list<std::string_view> required = {}) {
  for (const auto& field : value)
    require(std::find(allowed.begin(), allowed.end(), std::string_view(field.key())) != allowed.end(),
            "Unknown field: " + std::string(field.key()));
  for (const auto& field : required)
    require(value.contains(field), "Missing required field: " + std::string(field));
}
inline std::string string(const json::value& value, const std::string& context) {
  require(value.is_string(), context + " must be a string");
  return std::string(value.as_string());
}
inline std::uint64_t uint(const json::value& value, const std::string& context) {
  require(value.is_uint64() || (value.is_int64() && value.as_int64() >= 0),
          context + " must be a nonnegative integer");
  return value.is_uint64() ? value.as_uint64() : static_cast<std::uint64_t>(value.as_int64());
}
inline ExternalId external_id(const json::value& value) {
  if (value.is_string()) {
    require(!value.as_string().empty(), "IDs must not be empty");
    return ExternalId(std::string(value.as_string()));
  }
  require(value.is_int64() || (value.is_uint64() && value.as_uint64() <= INT64_MAX),
          "IDs must be strings or signed 64-bit integers; no floating-point conversion is allowed");
  return ExternalId(value.is_int64() ? value.as_int64() : static_cast<std::int64_t>(value.as_uint64()));
}
inline json::value id_json(const ExternalId& id) {
  return std::visit([](const auto& value) { return json::value(value); }, id.value());
}
}  // namespace graphmine::view_json
