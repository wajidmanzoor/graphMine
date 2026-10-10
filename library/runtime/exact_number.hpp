#pragma once

#include "internal.hpp"
#include <boost/multiprecision/cpp_int.hpp>
#include <cmath>
#include <limits>

namespace graphmine::runtime {
using Exact = boost::multiprecision::cpp_rational;
using Integer = boost::multiprecision::cpp_int;
inline Exact exact_number(const json::value& value, const std::string& context) {
  if (value.is_int64()) return Exact(value.as_int64());
  if (value.is_uint64()) return Exact(value.as_uint64());
  return Exact(number(value, context));
}

inline json::object fraction_json(const Exact& value) {
  return {{"numerator", numerator(value).convert_to<std::string>()},
          {"denominator", denominator(value).convert_to<std::string>()}};
}
// Exact CPU arithmetic uses the binary64 edge values admitted by Graph. Keep
// the full rational alongside a convenient numeric display; never overflow a
// reachable distance into the null value used for unreachable vertices.
inline json::value display_number(const Exact& value) {
  const auto n = numerator(value), d = denominator(value);
  if (d == 1 && n >= INT64_MIN && n <= INT64_MAX) return n.convert_to<std::int64_t>();
  if (d == 1 && n >= 0 && n <= UINT64_MAX) return n.convert_to<std::uint64_t>();
  const auto approximate = value.convert_to<double>();
  if (std::isfinite(approximate)) return approximate;
  return fraction_json(value);
}
inline void exact_field(json::object& row, const char* field, const Exact& value) {
  auto display = display_number(value);
  row[field] = display;
  row[std::string(field) + "_exact"] = fraction_json(value);
  row[std::string(field) + "_rounded"] = display.is_double() && Exact(display.as_double()) != value;
}
}  // namespace graphmine::runtime
