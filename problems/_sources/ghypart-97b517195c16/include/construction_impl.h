#pragma once
#include "graph.h"
#include "../utility/param_config.h"

void constructHgr(Hypergraph* hgr, Hypergraph* coarsenHgr, float& time, int iter, OptionConfigs& optcfgs);
