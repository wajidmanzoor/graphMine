#include <boost/json/basic_parser_impl.hpp>
#include <cmath>
#include <limits>
#include <set>

#include "internal.hpp"

namespace graphmine::runtime {
namespace {
// Validate original tokens before constructing the Boost.JSON DOM. Its normal
// parser represents overflowing integer literals as doubles; that would change
// attributes and make distinct inputs share a fingerprint before Graph sees them.
struct InputGuard {
  static constexpr std::size_t max_array_size = std::numeric_limits<std::size_t>::max();
  static constexpr std::size_t max_object_size = max_array_size;
  static constexpr std::size_t max_string_size = max_array_size;
  static constexpr std::size_t max_key_size = max_array_size;
  std::vector<std::set<std::string>> objects;
  std::string key, number;
  bool on_document_begin(boost::system::error_code&) { return true; }
  bool on_document_end(boost::system::error_code&) { return true; }
  bool on_array_begin(boost::system::error_code&) { return true; }
  bool on_array_end(std::size_t, boost::system::error_code&) { return true; }
  bool on_object_begin(boost::system::error_code&) {
    objects.emplace_back();
    return true;
  }
  bool on_object_end(std::size_t, boost::system::error_code&) {
    objects.pop_back();
    return true;
  }
  bool on_string_part(json::string_view, std::size_t, boost::system::error_code&) { return true; }
  bool on_string(json::string_view, std::size_t, boost::system::error_code&) { return true; }
  bool on_key_part(json::string_view part, std::size_t, boost::system::error_code&) {
    key.append(part.data(), part.size());
    return true;
  }
  bool on_key(json::string_view part, std::size_t, boost::system::error_code&) {
    key.append(part.data(), part.size());
    require(objects.back().insert(key).second, "Duplicate JSON object key: " + key);
    key.clear();
    return true;
  }
  bool on_number_part(json::string_view part, boost::system::error_code&) {
    number.append(part.data(), part.size());
    return true;
  }
  bool on_int64(std::int64_t, json::string_view, boost::system::error_code&) {
    number.clear();
    return true;
  }
  bool on_uint64(std::uint64_t, json::string_view, boost::system::error_code&) {
    number.clear();
    return true;
  }
  bool on_double(double value, json::string_view part, boost::system::error_code&) {
    number.append(part.data(), part.size());
    require(number.find_first_of(".eE") != std::string::npos,
            "Integer literal exceeds the native JSON integer range; use explicit string data until "
            "wider integer support is available");
    require(std::isfinite(value), "JSON numeric values must be finite");
    number.clear();
    return true;
  }
  bool on_bool(bool, boost::system::error_code&) { return true; }
  bool on_null(boost::system::error_code&) { return true; }
  bool on_comment_part(json::string_view, boost::system::error_code&) { return true; }
  bool on_comment(json::string_view, boost::system::error_code&) { return true; }
};
}  // namespace

json::value strict_json(std::string_view raw) {
  if (raw.size() > 64 * 1024 * 1024)
    throw Failure("resource_limit", "Native JSON input exceeds 64 MiB");
  json::basic_parser<InputGuard> guard(json::parse_options{});
  boost::system::error_code error;
  const auto consumed = guard.write_some(false, raw.data(), raw.size(), error);
  require(!error, "Invalid JSON input: " + error.message());
  require(consumed == raw.size(), "Unexpected text after JSON input");
  return json::parse(raw);
}
}  // namespace graphmine::runtime
