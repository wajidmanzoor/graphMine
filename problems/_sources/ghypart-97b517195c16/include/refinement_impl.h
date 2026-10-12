#pragma once
#include "graph.h"
#include "../utility/param_config.h"

void parallel_refine(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, int cur_iter, OptionConfigs& optcfgs);

void parallel_balance(Hypergraph* hgr, float ratio, unsigned int K, float imbalance,
                    float& time, float& cur, int& rebalance, int cur_iter, OptionConfigs& optcfgs);

void refinement_opt1(Hypergraph* hgr, unsigned refineTo, unsigned int K, float imbalance, 
                    float& time, float& cur, int cur_iter, float ratio, int iterNum, OptionConfigs& optcfgs);

void rebalancing_opt1(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, 
                    float& time, float& cur, int& rebalance, int cur_iter, int iterNum, OptionConfigs& optcfgs);

void refinement_opt2(Hypergraph* hgr, unsigned refineTo, unsigned int K, float imbalance, 
                    float& time, float& cur, int cur_iter, float ratio, int iterNum, OptionConfigs& optcfgs);

void rebalancing_opt2(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, 
                    float& time, float& cur, int& rebalance, int cur_iter, int iterNum, OptionConfigs& optcfgs);

void refinement_opt3(Hypergraph* hgr, unsigned refineTo, unsigned int K, float imbalance, 
                    float& time, float& cur, int cur_iter, float ratio, int iterNum, OptionConfigs& optcfgs);

void rebalancing_opt3(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, 
                    float& time, float& cur, int& rebalance, int cur_iter, int iterNum, OptionConfigs& optcfgs);

void refinement_opt4(Hypergraph* hgr, unsigned refineTo, unsigned int K, float imbalance, 
                    float& time, float& cur, int cur_iter, float ratio, int iterNum, OptionConfigs& optcfgs);

void rebalancing_opt4(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, 
                    float& time, float& cur, int& rebalance, int cur_iter, int iterNum, OptionConfigs& optcfgs);
