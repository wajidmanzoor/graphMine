#pragma once
#include "family_util.hpp"

namespace graphmine::runtime {
struct AnomalyInput {
  std::vector<family_util::Edge> simple,weighted,records;
  MiningGraph adjacency;
};
AnomalyInput anomaly_input(const Graph&, Work&);
std::vector<json::object> anomaly_records(const Graph&, bool vertices, Work&);
}
