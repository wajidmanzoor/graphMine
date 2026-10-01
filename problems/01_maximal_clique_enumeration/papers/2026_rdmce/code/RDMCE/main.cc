
#include <iostream>
#include <cstring>
#include <unistd.h>
#include "graph.h"
#include "mce_gpu.cuh"

void parseCommandLineArgs(int argc, char *argv[], std::string &input_file, OrderType &order, std::vector<int> &device_ids, bool &convert_only);
void printParameters(const std::string &input_file, OrderType order, std::vector<int> device_ids);
void loadGraph(Graph &g, const std::string &input_file, Timer &t);
void sortGraph(Graph &g, OrderType order, Timer &t);

int main(int argc, char *argv[]){
  std::string input_file = "";       // Default input file path
  OrderType order = OrderType::DEG;                     // Default order type
  std::vector<int> device_ids;                          // Default device ID
  bool convert_only = false;                            // Default: do not convert only

  parseCommandLineArgs(argc, argv, input_file, order, device_ids, convert_only);
  printParameters(input_file, order, device_ids);

  Graph g;
  Timer t;

  loadGraph(g, input_file, t);
  if (input_file.size() >= 4 && input_file.substr(input_file.size() - 4) != ".bin"){
    sortGraph(g, order, t);
    if(convert_only) {
      g.StoreIntoBin(input_file);
      std::cout << "preprocess " << input_file << " done" << std::endl;
    }
  }
  
  std::cout << "vertices: " << g.GetNumVertices() << " " << "\tedges: " << g.GetNumEdges() << std::endl;
  std::cout << "max degree: " << g.GetMaxDegree() << " " << "\tdegeneracy: " << g.GetDegeneracy() << std::endl;
  
  // If convert only mode is enabled, exit after conversion
  if (convert_only) {
    std::cout << "Convert only mode (-c) enabled, exiting after conversion." << std::endl;
    return 0;
  }

  if(device_ids.size() < 2){
    auto device_id = device_ids.empty()? 0 : device_ids[0];
    MceGpuSolver solver(g, device_id);
    solver.Solve();
  }
  else{
    GmceMultiGpuSolve(g, device_ids);
  }

  return 0;
}

// Function implementation to parse command line arguments
void parseCommandLineArgs(int argc, char *argv[], std::string &input_file, OrderType &order, std::vector<int> &device_ids, bool &convert_only)
{
  int opt;
  bool has_error = false;
  while ((opt = getopt(argc, argv, "i:o:d:c")) != -1)
  {
    switch (opt)
    {
    case 'i':
      input_file = optarg;
      break;
    case 'o':
      if (std::strcmp(optarg, "a") == 0)
      {
        order = OrderType::ASC;
      }
      else if (std::strcmp(optarg, "d") == 0)
      {
        order = OrderType::DES;
      }
      else if (std::strcmp(optarg, "deg") == 0)
      {
        order = OrderType::DEG;
      }
      else if (std::strcmp(optarg, "unchange") == 0)
      {
        order = OrderType::UNCHANGED;
      }
      else
      {
        has_error = true;
      }
      break;

    case 'd': {
        std::string ids_str = optarg;
        std::stringstream ss(ids_str);
        std::string id_str;
        device_ids.clear();
        
        while (std::getline(ss, id_str, ',')) {
            try {
                int id = std::stoi(id_str);
                if (id < 0) {
                    std::cerr << "invalid device ID: " << id << std::endl;
                    exit(1);
                }
                device_ids.push_back(id);
            } catch (const std::invalid_argument& e) {
                std::cerr << "invalid device ID: " << id_str << std::endl;
                exit(1);
            } catch (const std::out_of_range& e) {
                std::cerr << "invalid device ID: " << id_str << std::endl;
                exit(1);
            }
        }
        
        if (device_ids.empty()) {
            std::cerr << "-d option must provide at least one device ID" << std::endl;
            exit(1);
        }
        break;
    }
    case 'c':
      convert_only = true;
      break;
    default:
      has_error = true;
    }
  }
  if (input_file.empty())
    has_error = true;

  if (has_error)
  {
    std::cerr << "\033[33m" << "Usage: " << argv[0] << " -i <input_graph_file> -o <order_option> -d <device_ids> [-c]" << std::endl;
    std::cerr << "Order options: a (ascending), d (descending), deg (degeneracy),  unchange (unchanged)" << std::endl;
    std::cerr << "\033[36m" << "e.g., " << argv[0] << " -i RDMCE/data/zachary.txt -o deg -d 0" << "\033[0m" << std::endl;
    // std::cerr << "\033[36m" << "e.g., " << argv[0] << " -i ../data/zachary.txt -o deg -d 0 -c" << "\033[0m" << " (convert only)" << std::endl;
    exit(1);
  }
}

// Function implementation to print the parameters
void printParameters(const std::string &input_file, OrderType order, std::vector<int> device_ids)
{
  std::cout << "==================== Parameters ====================" << std::endl;
  std::cout << "Device ID: " ;
  for (auto id : device_ids) {
    std::cout << id << " ";
  }
  if(device_ids.empty())
    std::cout << "0";
  std::cout << std::endl;
  std::cout << "Input file: " << input_file << std::endl;
  std::cout << "Order type: ";
  switch (order)
  {
  case OrderType::ASC:
    std::cout << "Ascending";
    break;
  case OrderType::DES:
    std::cout << "Descending";
    break;
  case OrderType::DEG:
    std::cout << "Degeneracy";
    break;
  case OrderType::UNCHANGED:
    std::cout << "Unchanged";
    break;
  }
  std::cout << std::endl;
  std::cout << "Levels: ";
  #ifdef LEVEL_2
    std::cout << "L2";
  #else
    std::cout << "L1";
  #endif
  std::cout << std::endl;


  std::cout << "====================================================" << std::endl;
}

// Function implementation to load the graph
void loadGraph(Graph &g, const std::string &input_file, Timer &t)
{
  t.Start();
  if (input_file.size() >= 4 && input_file.substr(input_file.size() - 4) == ".bin") {
    g.LoadFromBin(input_file);
  } else {
    g.LoadFromFile(input_file);
  }
  t.Stop();
  std::cout << "Load time: " << t.Elapsed() << "s" << std::endl;
}

// Function implementation to sort the graph
void sortGraph(Graph &g, OrderType order, Timer &t)
{
  t.Start();
  g.SortByOrder(order);
  t.Stop();
  std::cout << "Sort time: " << t.Elapsed() << "s" << std::endl;
}