#include "internal.hpp"

#include <cudf/io/csv.hpp>
#include <cudf/strings/strings_column_view.hpp>
#include <cudf/table/table.hpp>
#include <cudf/utilities/default_stream.hpp>
#include <cudf/version_config.hpp>
#include <cuda_runtime_api.h>
#include <filesystem>
#include <map>
#include <set>

namespace graphmine::runtime {
namespace {
void cuda_check(cudaError_t status) {
  if (status != cudaSuccess) throw Failure("backend_failure", cudaGetErrorString(status));
}
struct SelectedDevice {
  int previous = 0;
  explicit SelectedDevice(int device) {
    cuda_check(cudaGetDevice(&previous));
    cuda_check(cudaSetDevice(device));
  }
  ~SelectedDevice() { cudaSetDevice(previous); }
};
template<class T> std::vector<T> host_values(const T* data, std::size_t size) {
  std::vector<T> output(size);
  if (size) cuda_check(cudaMemcpy(output.data(), data, size * sizeof(T), cudaMemcpyDeviceToHost));
  return output;
}
std::vector<std::string> strings(const cudf::column_view& column) {
  require(column.type().id() == cudf::type_id::STRING && column.null_count() == 0,
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
}

bool cudf_compiled() noexcept { return true; }
json::object read_csv(const json::object& request) {
  fields(request, {"command", "path", "columns", "gpu_device", "max_rows"}, {"command", "path", "columns"});
  const auto path = string(request.at("path"), "path");
  require(!path.empty(), "CSV path must not be empty");
  require(std::filesystem::is_regular_file(path), "CSV input must be a regular local file");
  const auto bytes = std::filesystem::file_size(path);
  if (bytes > 64 * 1024 * 1024) throw Failure("resource_limit", "CSV file exceeds the current 64 MiB ingestion profile");
  const auto ordinal = request.contains("gpu_device") ? uint(request.at("gpu_device"), "gpu_device") : 0;
  require(ordinal <= INT32_MAX, "gpu_device is out of range");
  const auto max_rows = request.contains("max_rows") ? uint(request.at("max_rows"), "max_rows") : 100000;
  require(max_rows > 0, "max_rows must be positive");
  require(request.at("columns").is_array() && !request.at("columns").as_array().empty(), "Declare all CSV column names explicitly");
  std::map<std::string, cudf::data_type> types;
  for (const auto& value : request.at("columns").as_array()) {
    const auto name = string(value, "column name");
    require(!name.empty() && types.emplace(name, cudf::data_type(cudf::type_id::STRING)).second, "Column names must be nonempty and unique");
  }
  SelectedDevice selected(static_cast<int>(ordinal));
  // Parse on the GPU. Read text explicitly: account 001 must not become 1,
  // large integer IDs must not become doubles, and NA is a valid domain string.
  auto options = cudf::io::csv_reader_options::builder(cudf::io::source_info(path))
                     .header(0).dtypes(types).keep_default_na(false).na_filter(false).build();
  auto loaded = cudf::io::read_csv(options);
  const auto table = loaded.tbl->view();
  if (static_cast<std::uint64_t>(table.num_rows()) > max_rows) throw Failure("resource_limit", "CSV row limit exceeded; no truncated table was returned");
  require(loaded.metadata.schema_info.size() == types.size(), "CSV header does not match the declared column set");
  std::vector<std::string> names;
  std::vector<std::vector<std::string>> columns;
  json::array schemas, rows;
  std::set<std::string> seen;
  for (std::size_t i = 0; i < loaded.metadata.schema_info.size(); ++i) {
    const auto name = loaded.metadata.schema_info[i].name;
    require(types.count(name) && seen.insert(name).second, "CSV header does not match the declared column set");
    names.push_back(name);
    schemas.push_back(json::object{{"name", name}, {"type", "string"}, {"nullable", false}});
    columns.push_back(strings(table.column(static_cast<cudf::size_type>(i))));
  }
  for (cudf::size_type i = 0; i < table.num_rows(); ++i) {
    json::object row;
    for (std::size_t c = 0; c < names.size(); ++c) row[names[c]] = columns[c][i];
    rows.push_back(row);
  }
  return {{"table", {{"columns", schemas}, {"rows", rows}}}, {"complete", true},
          {"provenance", {{"reader", "libcudf"}, {"version", CUDF_VERSION}, {"device", "gpu"},
                          {"gpu_device", ordinal}, {"input_bytes", bytes},
                          {"header_policy", "cudf_unique_names_must_match_declared_columns"},
                          {"value_policy", "text_preserved; explicit conversion required for graph weights and numeric IDs"},
                          {"python_runtime_required", false}}}};
}
}  // namespace graphmine::runtime
