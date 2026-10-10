#include "graphmine/runtime.hpp"
#include <boost/json.hpp>
#include <fstream>
#include <iostream>
#include <string>

namespace {
std::string read(const std::string& path) {
  std::ifstream file;
  if (path != "-") { file.open(path, std::ios::binary); if (!file) throw std::runtime_error("Cannot open input file"); }
  std::istream& input = path == "-" ? std::cin : file;
  std::string result;
  char block[8192];
  while (input.read(block, sizeof(block)) || input.gcount()) {
    result.append(block, static_cast<std::size_t>(input.gcount()));
    if (result.size() > 64 * 1024 * 1024) throw std::runtime_error("File exceeds 64 MiB request limit");
  }
  if (input.bad()) throw std::runtime_error("Input read failed");
  return result;
}
}
int main(int argc, char** argv) {
  namespace json = boost::json;
  try {
    json::object request;
    const std::string command = argc > 1 ? argv[1] : "";
    if ((command == "list" || command == "families" || command == "catalog") && argc == 2) request = {{"command", "catalog"}};
    else if (command == "request" && argc == 2) {
      const auto response = graphmine::runtime::request(read("-"));
      std::cout << response << '\n';
      return json::parse(response).as_object().contains("error") ? 2 : 0;
    } else if ((command == "read-csv" || command == "read-graph") && argc >= 3) {
      request = {{"command", command == "read-csv" ? "read_csv" : "read_graph"}, {"path", argv[2]}};
      for (int i = 3; i < argc; i += 2) {
        if (i + 1 >= argc) throw std::runtime_error("Missing option value");
        const std::string flag = argv[i], value = argv[i + 1];
        if (flag == "--columns") request["columns"] = json::parse(read(value));
        else if (flag == "--gpu-device") request["gpu_device"] = json::parse(value);
        else if (flag == "--max-rows") request["max_rows"] = json::parse(value);
        else if (flag == "--directed") request["directed"] = json::parse(value);
        else if (flag == "--source-column") request["source_column"] = value;
        else if (flag == "--target-column") request["target_column"] = value;
        else if (flag == "--id-type") request["id_type"] = value;
        else throw std::runtime_error("Unknown CSV option: " + flag);
      }
    } else if (command == "run" && argc >= 4) {
      request = {{"command", "run"}, {"operation", argv[2]}, {"graph", json::parse(read(argv[3]))}};
      for (int i = 4; i < argc; i += 2) {
        if (i + 1 >= argc) throw std::runtime_error("Missing option value");
        const std::string flag = argv[i], value = argv[i + 1];
        if (flag == "--parameters" || flag == "--budget") request[flag.substr(2)] = json::parse(read(value));
        else if (flag == "--device" || flag == "--backend") request[flag.substr(2)] = value;
        else if (flag == "--gpu-device") request["gpu_device"] = json::parse(value);
        else throw std::runtime_error("Unknown option: " + flag);
      }
    } else throw std::runtime_error("Usage: graphmine-native catalog|list|families|request; run OP GRAPH.json [--parameters PARAMS.json] [--device cpu|gpu|auto] [--backend ID] [--gpu-device N] [--budget BUDGET.json]; read-csv FILE [--columns NAMES.json] [--gpu-device N] [--max-rows N]; read-graph FILE.csv|FILE.txt [--source-column NAME] [--target-column NAME] [--directed true|false] [--id-type canonical|string] [--gpu-device N] [--max-rows N]");
    auto response = json::parse(graphmine::runtime::request(json::serialize(request))).as_object();
    if (response.contains("error")) { std::cout << json::serialize(response) << '\n'; return 2; }
    if (command == "list") std::cout << json::serialize(response.at("operations")) << '\n';
    else if (command == "families") std::cout << json::serialize(response.at("families")) << '\n';
    else std::cout << json::serialize(response) << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << json::serialize(json::object{{"error", {{"code", "invalid_input"}, {"message", error.what()}}}}) << '\n';
    return 2;
  }
}
