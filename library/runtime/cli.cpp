#include <boost/json.hpp>
#include <cerrno>
#include <cstdio>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <string>
#include <unistd.h>

#include "graphmine/runtime.hpp"
#include "internal.hpp"

namespace {
// Research kernels can print directly from C/CUDA, including during teardown.
// Keep their diagnostics on stderr and reserve a separate fd for JSON output.
class ProtocolOutput {
 public:
  ProtocolOutput() : descriptor_(dup(STDOUT_FILENO)) {
    std::cout.flush();
    std::fflush(stdout);
    if (descriptor_ < 0) throw std::runtime_error("Cannot open protocol output");
    if (fcntl(descriptor_, F_SETFD, FD_CLOEXEC) < 0 ||
        dup2(STDERR_FILENO, STDOUT_FILENO) < 0) {
      close(descriptor_);
      throw std::runtime_error("Cannot redirect native diagnostics");
    }
  }
  ~ProtocolOutput() { close(descriptor_); }
  ProtocolOutput(const ProtocolOutput&) = delete;
  ProtocolOutput& operator=(const ProtocolOutput&) = delete;
  void emit(const std::string& value) const {
    const auto line = value + '\n';
    std::size_t offset = 0;
    while (offset < line.size()) {
      const auto count = write(descriptor_, line.data() + offset, line.size() - offset);
      if (count < 0 && errno == EINTR) continue;
      if (count <= 0) throw std::runtime_error("Cannot write protocol output");
      offset += static_cast<std::size_t>(count);
    }
  }

 private:
  int descriptor_;
};

std::string read(const std::string& path) {
  std::ifstream file;
  if (path != "-") {
    file.open(path, std::ios::binary);
    if (!file) throw std::runtime_error("Cannot open input file");
  }
  std::istream& input = path == "-" ? std::cin : file;
  std::string result;
  char block[8192];
  while (input.read(block, sizeof(block)) || input.gcount()) {
    result.append(block, static_cast<std::size_t>(input.gcount()));
    if (result.size() > 64 * 1024 * 1024)
      throw std::runtime_error("File exceeds 64 MiB request limit");
  }
  if (input.bad()) throw std::runtime_error("Input read failed");
  return result;
}

void filter_family(boost::json::object& catalog, const std::string& selected) {
  namespace json = boost::json;
  bool known = false;
  std::string valid;
  for (const auto& row : catalog.at("families").as_array()) {
    const auto id = graphmine::runtime::string(row.as_object().at("id"), "family");
    if (!valid.empty()) valid += ", ";
    valid += id;
    known = known || id == selected;
  }
  if (!known)
    throw std::runtime_error("Unknown native family '" + selected + "'. Valid families: " + valid);
  for (const auto* key : {"families", "operations", "problems"}) {
    json::array rows;
    const auto* field = std::string(key) == "families" ? "id" : "family";
    for (const auto& row : catalog.at(key).as_array()) {
      const auto* family = row.as_object().if_contains(field);
      if (family && family->as_string() == selected) rows.push_back(row);
    }
    catalog[key] = std::move(rows);
  }
}
}  // namespace
int main(int argc, char** argv) {
  namespace json = boost::json;
  try {
    ProtocolOutput protocol;
    json::object request;
    std::optional<std::string> family;
    const std::string command = argc > 1 ? argv[1] : "";
    if (command == "list" || command == "families" || command == "catalog") {
      request = {{"command", "catalog"}};
      if (argc == 4 && std::string(argv[2]) == "--family")
        family = argv[3];
      else if (argc != 2)
        throw std::runtime_error("Usage: graphmine-native " + command + " [--family ID]");
    } else if (command == "request" && argc == 2) {
      const auto response = graphmine::runtime::request(read("-"));
      protocol.emit(response);
      return json::parse(response).as_object().contains("error") ? 2 : 0;
    } else if ((command == "read-csv" || command == "read-graph") && argc >= 3) {
      request = {{"command", command == "read-csv" ? "read_csv" : "read_graph"}, {"path", argv[2]}};
      for (int i = 3; i < argc; i += 2) {
        if (i + 1 >= argc) throw std::runtime_error("Missing option value");
        const std::string flag = argv[i], value = argv[i + 1];
        if (flag == "--columns")
          request["columns"] = graphmine::runtime::strict_json(read(value));
        else if (flag == "--gpu-device")
          request["gpu_device"] = graphmine::runtime::strict_json(value);
        else if (flag == "--max-rows")
          request["max_rows"] = graphmine::runtime::strict_json(value);
        else if (flag == "--directed")
          request["directed"] = graphmine::runtime::strict_json(value);
        else if (flag == "--source-column")
          request["source_column"] = value;
        else if (flag == "--target-column")
          request["target_column"] = value;
        else if (flag == "--id-type")
          request["id_type"] = value;
        else
          throw std::runtime_error("Unknown CSV option: " + flag);
      }
    } else if (command == "run" && argc >= 4) {
      request = {{"command", "run"},
                 {"operation", argv[2]},
                 {"graph", graphmine::runtime::strict_json(read(argv[3]))}};
      for (int i = 4; i < argc; i += 2) {
        if (i + 1 >= argc) throw std::runtime_error("Missing option value");
        const std::string flag = argv[i], value = argv[i + 1];
        if (flag == "--parameters" || flag == "--budget")
          request[flag.substr(2)] = graphmine::runtime::strict_json(read(value));
        else if (flag == "--device" || flag == "--backend")
          request[flag.substr(2)] = value;
        else if (flag == "--gpu-device")
          request["gpu_device"] = graphmine::runtime::strict_json(value);
        else
          throw std::runtime_error("Unknown option: " + flag);
      }
    } else
      throw std::runtime_error(
          "Usage: graphmine-native catalog|list|families [--family ID]; request; run OP GRAPH.json [--parameters "
          "PARAMS.json] [--device cpu|gpu|auto] [--backend ID] [--gpu-device N] [--budget "
          "BUDGET.json]; read-csv FILE [--columns NAMES.json] [--gpu-device N] [--max-rows N]; "
          "read-graph FILE.csv|FILE.txt [--source-column NAME] [--target-column NAME] [--directed "
          "true|false] [--id-type canonical|string] [--gpu-device N] [--max-rows N]");
    auto response = json::parse(graphmine::runtime::request(json::serialize(request))).as_object();
    if (response.contains("error")) {
      protocol.emit(json::serialize(response));
      return 2;
    }
    if (family) filter_family(response, *family);
    if (command == "list")
      protocol.emit(json::serialize(response.at("operations")));
    else if (command == "families")
      protocol.emit(json::serialize(response.at("families")));
    else
      protocol.emit(json::serialize(response));
    return 0;
  } catch (const std::exception& error) {
    std::cerr << json::serialize(json::object{
                     {"error", {{"code", "invalid_input"}, {"message", error.what()}}}})
              << '\n';
    return 2;
  }
}
