#include <graphmine/runtime.hpp>
#include <iostream>

int main() {
  // Link the installed C++ core and execute an algorithm without Python.
  std::cout << graphmine::runtime::request(R"({
    "command":"run", "operation":"maximum-clique", "device":"cpu",
    "parameters":{"return_all_ties":true},
    "graph":{
      "graph":{"id":"native-consumer","directed":false,"allows_self_loops":false,"allows_parallel_edges":false},
      "vertices":[{"id":0},{"id":1},{"id":2},{"id":3}],
      "edges":[{"id":0,"source":0,"target":1},{"id":1,"source":1,"target":2},{"id":2,"source":2,"target":0}]
    }
  })");
}
