#include "internal.hpp"
#include "catalog_data.hpp"

#include <cudf/io/csv.hpp>
#include <cudf/io/datasource.hpp>
#include <cudf/strings/strings_column_view.hpp>
#include <cudf/table/table.hpp>
#include <cudf/utilities/default_stream.hpp>
#include <cudf/version_config.hpp>
#include <cuda_runtime_api.h>
#include <openssl/sha.h>
#include <algorithm>
#include <filesystem>
#include <iomanip>
#include <set>
#include <sstream>

namespace graphmine::runtime {
namespace {
void cuda_check(cudaError_t status) {
  if (status != cudaSuccess) throw Failure("backend_failure", cudaGetErrorString(status));
}
template<class T> std::vector<T> host_values(const T* data, std::size_t size) {
  std::vector<T> output(size);
  if (size) cuda_check(cudaMemcpy(output.data(), data, size * sizeof(T), cudaMemcpyDeviceToHost));
  return output;
}
std::vector<std::string> strings(const cudf::column_view& column, bool allow_missing) {
  require(column.type().id() == cudf::type_id::STRING && (allow_missing || column.null_count() == 0),
          "CSV columns must retain their text without implicit missing-value conversion");
  if (!column.size()) return {};
  const cudf::strings_column_view view(column);
  const auto stream = cudf::get_default_stream();
  const auto chars = host_values(view.chars_begin(stream), static_cast<std::size_t>(view.chars_size(stream)));
  std::vector<std::int64_t> offsets;
  if (view.offsets().type().id() == cudf::type_id::INT32) {
    const auto values = host_values(view.offsets().data<std::int32_t>(), column.size() + 1);
    offsets.assign(values.begin(), values.end());
  } else if (view.offsets().type().id() == cudf::type_id::INT64) {
    offsets = host_values(view.offsets().data<std::int64_t>(), column.size() + 1);
  } else throw Failure("backend_failure", "Unsupported libcudf string offset type");
  std::vector<std::string> result;
  for (std::size_t i = 0; i < static_cast<std::size_t>(column.size()); ++i) {
    require(offsets[i] >= 0 && offsets[i] <= offsets[i + 1] && static_cast<std::size_t>(offsets[i + 1]) <= chars.size(), "Invalid libcudf string offsets");
    if (offsets[i] == offsets[i + 1]) result.emplace_back();
    else result.emplace_back(chars.data() + offsets[i], offsets[i + 1] - offsets[i]);
  }
  return result;
}
bool space(char c) { return c == ' ' || c == '\t'; }
std::string trim(std::string value) {
  const auto start = value.find_first_not_of(" \t\r\n");
  return start == std::string::npos ? "" : value.substr(start, value.find_last_not_of(" \t\r\n") - start + 1);
}
std::string lower(std::string value) {
  for (auto& c : value) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + 'a' - 'A');
  return value;
}
void validate_utf8(std::string_view text) {
  for (std::size_t i = 0; i < text.size();) {
    auto c = static_cast<unsigned char>(text[i++]);
    require(c != 0, "Delimited input must not contain NUL bytes");
    if (c < 0x80) continue;
    const int length = c >= 0xC2 && c <= 0xDF ? 2 : c >= 0xE0 && c <= 0xEF ? 3 : c >= 0xF0 && c <= 0xF4 ? 4 : 0;
    require(length && i + length - 1 <= text.size(), "Delimited input must be UTF-8");
    std::uint32_t point = c & (length == 2 ? 31 : length == 3 ? 15 : 7);
    for (int n = 1; n < length; ++n) {
      c = static_cast<unsigned char>(text[i++]);
      require((c & 0xC0) == 0x80, "Delimited input must be UTF-8");
      point = (point << 6) | (c & 63);
    }
    require(point >= (length == 2 ? 0x80u : length == 3 ? 0x800u : 0x10000u) &&
            point <= 0x10FFFF && !(point >= 0xD800 && point <= 0xDFFF), "Delimited input must be UTF-8");
  }
}
struct Shape { std::size_t width = 0, records = 0; };
// cuDF tolerates extra CSV fields. Validate record structure before GPU parsing
// so fields cannot silently disappear. libcudf alone decodes cell values.
Shape validate_shape(std::string_view text, bool whitespace, bool edge_list, std::uint64_t max_rows) {
  enum State { start, unquoted, quoted, closed } state = start;
  Shape shape;
  std::size_t fields = 0, cells = 0;
  bool active = false;
  auto finish = [&] {
    if (active) {
      const auto width = fields + ((state != start || !whitespace) ? 1 : 0);
      require(width > 0 && width <= 4096, "Delimited input exceeds the 4,096-column profile");
      if (edge_list) require(width >= 2 && width <= 4, "edge-list row needs source target [weight] [timestamp]");
      else require(!shape.records || shape.width == width, "CSV record has a different number of values than its header");
      shape.width = std::max(shape.width, width);
      ++shape.records; cells += width;
      if (shape.records > max_rows + 1 || cells > 1000000) throw Failure("resource_limit", "Delimited row limit or 1,000,000-cell profile exceeded");
    }
    state = start; fields = 0; active = false;
  };
  for (std::size_t i = 0; i < text.size(); ++i) {
    const auto c = text[i];
    if (state == quoted) {
      if (c == '"') {
        if (i + 1 < text.size() && text[i + 1] == '"') ++i;
        else state = closed;
      }
      require(!edge_list || (c != '\n' && c != '\r'), "Edge-list quoted fields must stay on one line");
      continue;
    }
    if (c == '\n' || c == '\r') {
      if (c == '\r') {
        require(i + 1 < text.size() && text[i + 1] == '\n', "Delimited records require LF or CRLF line endings");
        ++i;
      }
      finish(); continue;
    }
    if ((!whitespace && c == ',') || (whitespace && space(c))) {
      if (!whitespace || state != start) ++fields;
      state = start;
      if (!whitespace) active = true;
      continue;
    }
    require(state != closed, "CSV characters follow a closing quote");
    if (c == '"') {
      require(state == start, "CSV quotes must enclose the entire field");
      state = quoted; active = true;
    } else {
      state = unquoted;
      if (!space(c)) active = true;
    }
  }
  require(state != quoted, "CSV quoted field is unterminated");
  finish();
  require(shape.records > 0, "Delimited input contains no records");
  return shape;
}
std::string edge_records(std::string_view text) {
  std::string result;
  for (std::size_t i = 0; i < text.size();) {
    auto end = text.find('\n', i);
    if (end == std::string_view::npos) end = text.size();
    auto line = trim(std::string(text.substr(i, end - i)));
    if (!line.empty() && line[0] != '#' && line[0] != '%') { result += line; result += '\n'; }
    i = end + 1;
  }
  return result;
}
bool comma_separated(std::string_view text) {
  bool quoted = false;
  for (const auto c : text) {
    if (c == '"') quoted = !quoted;
    if (!quoted && c == ',') return true;
    if (!quoted && c == '\n') break;
  }
  return false;
}
std::string digest(std::string_view bytes) {
  unsigned char hash[SHA256_DIGEST_LENGTH];
  SHA256(reinterpret_cast<const unsigned char*>(bytes.data()), bytes.size(), hash);
  std::ostringstream output;
  for (const auto c : hash) output << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(c);
  return output.str();
}
}  // namespace

bool cudf_compiled() noexcept { return true; }
json::object read_csv(const json::object& request) {
  fields(request, {"command", "path", "columns", "gpu_device", "max_rows", "format"}, {"command", "path"});
  const auto path = string(request.at("path"), "path");
  require(!path.empty() && std::filesystem::is_regular_file(path), "Delimited input must be a regular local file");
  const auto bytes = std::filesystem::file_size(path);
  require(bytes > 0, "Delimited input is empty");
  if (bytes > 64 * 1024 * 1024) throw Failure("resource_limit", "File exceeds the current 64 MiB ingestion profile");
  const auto ordinal = request.contains("gpu_device") ? uint(request.at("gpu_device"), "gpu_device") : 0;
  require(ordinal <= INT32_MAX, "gpu_device is out of range");
  const auto max_rows = request.contains("max_rows") ? uint(request.at("max_rows"), "max_rows") : 100000;
  require(max_rows > 0 && max_rows <= 1000000, "max_rows must be between 1 and 1,000,000");
  const auto format = request.contains("format") ? string(request.at("format"), "format") : "csv";
  require(format == "csv" || format == "edge_list", "Unsupported delimited format");
  const bool edge_list = format == "edge_list";
  // cuDF provides file IO; its GPU parser decodes all values, including headers.
  auto source = cudf::io::datasource::create(path);
  require(source->size() == bytes, "File changed during ingestion");
  auto buffer = source->host_read(0, static_cast<std::size_t>(bytes));
  require(buffer->size() == bytes, "Input read was incomplete");
  const auto original = std::string_view(reinterpret_cast<const char*>(buffer->data()), buffer->size());
  validate_utf8(original);
  auto text = std::string(original);
  if (text.substr(0, 3) == "\xEF\xBB\xBF") text.erase(0, 3);
  if (edge_list) text = edge_records(text);
  const bool whitespace = edge_list && !comma_separated(text);
  const auto shape = validate_shape(text, whitespace, edge_list, max_rows);
  // libcudf's whitespace profile splits spaces. Normalize tab separators only
  // outside quoted fields; tabs inside an ID remain part of that ID.
  if (whitespace) {
    bool quoted = false;
    for (auto& c : text) {
      if (c == '"') quoted = !quoted;
      else if (c == '\t' && !quoted) c = ' ';
    }
  }
  DeviceScope selected(static_cast<int>(ordinal));
  std::vector<std::string> dense_names;
  for (std::size_t i = 0; i < shape.width; ++i) dense_names.push_back(std::to_string(i));
  auto options = cudf::io::csv_reader_options::builder(cudf::io::source_info(cudf::host_span<const char>{text.data(), text.size()}))
                     .header(-1).names(dense_names)
                     .compression(cudf::io::compression_type::NONE)
                     .dtypes(std::vector<cudf::data_type>(shape.width, cudf::data_type(cudf::type_id::STRING)))
                     .keep_default_na(false).na_filter(false).delim_whitespace(whitespace).build();
  auto loaded = cudf::io::read_csv(options);
  const auto table = loaded.tbl->view();
  require(static_cast<std::size_t>(table.num_rows()) == shape.records && static_cast<std::size_t>(table.num_columns()) == shape.width,
          "cuDF parsed a different record shape; no partial input was accepted");
  std::vector<std::vector<std::string>> columns;
  for (cudf::size_type i = 0; i < table.num_columns(); ++i) columns.push_back(strings(table.column(i), edge_list));
  const auto first = lower(trim(columns[0][0]));
  const bool header = !edge_list || first == "source" || first == "src" || first == "from";
  const std::size_t first_row = header ? 1 : 0;
  if (shape.records - first_row > max_rows) throw Failure("resource_limit", "CSV row limit exceeded; no truncated table was returned");
  if (edge_list) require(shape.records > first_row, "edge-list input contains no edges");
  std::vector<std::string> names;
  const std::vector<std::string> edge_names{"source", "target", "weight", "timestamp"};
  std::set<std::string> seen;
  for (std::size_t i = 0; i < shape.width; ++i) {
    const auto name = edge_list ? edge_names[i] : columns[i][0];
    require(!trim(name).empty() && seen.insert(name).second, "CSV column names must be nonempty and unique");
    names.push_back(name);
  }
  if (request.contains("columns")) {
    require(request.at("columns").is_array(), "columns must be an array");
    std::set<std::string> declared;
    for (const auto& value : request.at("columns").as_array())
      require(declared.insert(string(value, "column name")).second, "Declared column names must be unique");
    require(declared == seen, "CSV header does not match the declared column set");
  }
  json::array schemas, rows;
  for (const auto& name : names) schemas.push_back(json::object{{"name", name}, {"type", "string"}, {"nullable", false}});
  for (std::size_t i = first_row; i < shape.records; ++i) {
    json::object row;
    for (std::size_t c = 0; c < names.size(); ++c) row[names[c]] = columns[c][i];
    rows.push_back(std::move(row));
  }
  return {{"table", {{"columns", schemas}, {"rows", rows}}}, {"complete", true},
          {"provenance", {{"reader", "libcudf"}, {"version", CUDF_VERSION}, {"device", "gpu"},
                          {"gpu_device", ordinal}, {"input_bytes", bytes}, {"input_sha256", digest(original)},
                          {"implementation_sha256", implementation_sha256},
                          {"format", format}, {"header", header}, {"profile", "strict-delimited-v2"},
                          {"header_policy", "original_nonempty_unique_names"},
                          {"value_policy", "text_preserved; explicit conversion required for graph weights and numeric IDs"},
                          {"python_runtime_required", false}}}};
}
}  // namespace graphmine::runtime
