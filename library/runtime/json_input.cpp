#include "internal.hpp"
#include "../src/core/view_json.hpp"
namespace graphmine::runtime {
json::value strict_json(std::string_view raw) {
  try { return view_json::strict_json(raw); }
  catch (const std::length_error& error) { throw Failure("resource_limit", error.what()); }
  catch (const std::invalid_argument& error) { throw Failure("invalid_input", error.what()); }
}
}  // namespace graphmine::runtime
