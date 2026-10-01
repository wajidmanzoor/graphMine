// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
//
// Portions of this file are derived from the Jet: Multilevel Graph Partitioning project.
// Original license and copyright notices are retained below.
// ***********************************************************************
// 
// Jet: Multilevel Graph Partitioning
//
// Copyright 2023 National Technology & Engineering Solutions of Sandia, LLC
// (NTESS). 
// 
// Under the terms of Contract DE-AC04-94AL85000 with Sandia Corporation,
// the U.S. Government retains certain rights in this software.
// 
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are
// met:
//
// 1. Redistributions of source code must retain the above copyright
// notice, this list of conditions and the following disclaimer.
//
// 2. Redistributions in binary form must reproduce the above copyright
// notice, this list of conditions and the following disclaimer in the
// documentation and/or other materials provided with the distribution.
//
// 3. Neither the name of the Corporation nor the names of the
// contributors may be used to endorse or promote products derived from
// this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY SANDIA CORPORATION "AS IS" AND ANY
// EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
// PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL SANDIA CORPORATION OR THE
// CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
// EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
// PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
// PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
// LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
// NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
// SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
//
// ************************************************************************
#pragma once
#include <vector>
#include <stdlib.h>
#include <iostream>
#include <fstream>
#include <string>
#include <map>

namespace jet_community {

enum class Measurement : int {
	Contract,
    Coarsen,
    LeidenRefine,
    FreeGraph,
    Total,
	END
};

template <typename scalar_t>
class ExperimentLoggerUtil {

public:
	std::vector<std::string> measurementNames{
		"coarsen-contract",
        "coarsen",
        "leiden-refine",
        "free-graph",
        "total",
	};
	std::vector<double> measurements;

	class CoarseLevel {
	public:
        int64_t edge_cut = 0;
        double imb = 0;
        uint64_t numEdges = 0;
		uint64_t numVertices = 0;
        double totalRefTime = 0;
        double iterationsTime = 0;
        int totalIterations = 0;
        int lpIterations = 0;

		CoarseLevel(int64_t _edge_cut, double _imb, uint64_t _numEdges, uint64_t _numVertices, double _totalRefTime, double _iterationsTime, int _totalIterations, int _lpIterations) :
            edge_cut(_edge_cut),
            imb(_imb),
            numEdges(_numEdges),
			numVertices(_numVertices),
            totalRefTime(_totalRefTime),
            iterationsTime(_iterationsTime),
            totalIterations(_totalIterations),
            lpIterations(_lpIterations) {}

	};

private:
	int numCoarseLevels = 0;
	std::vector<CoarseLevel> coarseLevels;
	std::vector<double> iter_times;
	std::vector<double> iter_obj;
    scalar_t edge_cut = 0;
    double modularity = -1.0;
	int64_t t_nnz = 0;
	int level_count = 0;

public:
	ExperimentLoggerUtil() :
		measurements(static_cast<int>(Measurement::END), 0.0)
	{}

	void addCoarseLevel(CoarseLevel cl) {
		coarseLevels.push_back(cl);
		numCoarseLevels++;
	}

	void setEdgeCut(scalar_t _edge_cut) {
		edge_cut = _edge_cut;
	}

    void setModularity(double _modularity){
        modularity = _modularity;
    }

	void addMeasurement(Measurement m, double val) {
		measurements[static_cast<int>(m)] += val;
	}

	double getMeasurement(Measurement m) {
		return measurements[static_cast<int>(m)];
	}

	void setTotalNnz(int64_t _t_nnz){
		t_nnz = _t_nnz;
	}

	void setLevelCount(int _level_count){
		level_count = _level_count;
	}

	void add_iter_time(double iter_time){
		iter_times.push_back(iter_time);
	}

	void add_iter_obj(double obj){
		iter_obj.push_back(obj);
	}

	void log(const char* filename, bool first, bool last) {
		std::ofstream f;
		f.open(filename, std::ios::app);

		if (f.is_open()) {
			if (first) {
				f << "[";
			}
			f << "{";
            f << "\"edge-cut\":" << std::fixed << edge_cut << ",";
            f << "\"modularity\":" << modularity << ",";
            f << "\"total-nnz\":" << t_nnz << ",";
            f << "\"level-count\":" << level_count << ",";
			for (int i = 0; i < static_cast<int>(Measurement::END); i++) {
				f << "\"" << measurementNames[i] << "-duration-seconds\":" << measurements[i] << ",";
			}
			for(size_t i = 0; i < iter_times.size(); i++){
				f << "\"iter-times-" << i << "\":" << iter_times[i] << ",";
			}
			for(size_t i = 0; i < iter_obj.size(); i++){
				f << "\"iter-obj-" << i << "\":" << iter_obj[i] << ",";
			}
			f << "\"number-coarse-levels\":" << numCoarseLevels;
			f << "}";
			if (!last) {
				f << ",";
			}
			else {
				f << "]";
			}
			f.close();
		}
		else {
			std::cerr << "Could not open " << filename << std::endl;
		}
	}

    void refinementReport(){
        std::cout << std::setprecision(6);
        std::cout << std::left << std::setw(6) << "Level" << std::setw(16) << "Edge Cut" << std::setw(10) << "Imbalance";
        std::cout << std::setw(13) << "Vertices" << std::setw(16) << "Edges" << std::setw(22) << "Total Refinement Time";
        std::cout << std::setw(17) << "Total Iterations" << std::setw(14) << "LP Iterations" << std::setw(23) << "Average Iteration Time" << std::endl;
        for(size_t i = 0; i < coarseLevels.size(); i++){
            CoarseLevel cl = coarseLevels[i];
            int level = coarseLevels.size() - 1 - i;
            std::cout << std::fixed << std::left << std::setw(6) << level << std::setw(16) << cl.edge_cut << std::setw(10) << cl.imb;
            std::cout << std::setw(13) << cl.numVertices << std::setw(16) << cl.numEdges << std::setw(22) << cl.totalRefTime;
            std::cout << std::setw(17) << cl.totalIterations << std::setw(14) << cl.lpIterations << std::setw(23) << (cl.iterationsTime / cl.totalIterations) << std::endl;
        }
    }
};

}
