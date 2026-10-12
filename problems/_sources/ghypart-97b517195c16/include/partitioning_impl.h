#pragma once
#include "graph.h"
#include "../utility/param_config.h"

void partition_baseline(Hypergraph* hgr, unsigned int K, bool use_curr_precision, float& time, OptionConfigs& optcfgs);

void partition_opt1(Hypergraph* hgr, unsigned int K, bool use_curr_precision, float& time);

void partition_opt2(Hypergraph* hgr, unsigned int K, bool use_curr_precision, float& time);
