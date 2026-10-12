#pragma once
#include "graph.h"
#include "../utility/param_config.h"

Hypergraph* coarsen(Hypergraph* hgr, int iter, int LIMIT, float& time, OptionConfigs& optcfgs);
