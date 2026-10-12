#pragma once
#include <iostream>
#include <limits.h>
#include <sys/time.h>
#include <getopt.h>
#include <fstream>
#include <string>
#include <unordered_set>
#include <experimental/filesystem>
#include <vector>
#include "../include/graph.h"
#include "utils.cuh"
#include "param_config.h"

void coarsening_validation(Hypergraph* hgr, bool useUVM = true);

void initial_partitioning_validation(Hypergraph* hgr, bool useUVM = true);

void final_partitioning_validation(Hypergraph* hgr, Stats stats, bool useUVM = true);
