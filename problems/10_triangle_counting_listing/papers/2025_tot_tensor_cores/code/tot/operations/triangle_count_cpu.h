#pragma once

#include <iostream>
#include <vector>

namespace tot {

template<typename CsrMatrix>
auto bfs_tc(const CsrMatrix& mat)
{
    std::cout << "\n----------------bfs tc 3-------------" << std::endl;
    size_t      numTriangles = 0;
    const auto  numVertices  = mat.num_rows;
    const auto& rowPtr       = mat.row_pointers;
    const auto& colIdx       = mat.column_indices;
   // std::cout << "nodes: " << numVertices << " edges: " << colIdx.size() << '\n';
    // check if two nodes have an edge between them with binary search
    // (require sorted colIdx)
    auto intersect = [&](int first, int second) -> bool {
        auto first_begin = colIdx.begin() + rowPtr[first];
        auto first_end   = colIdx.begin() + rowPtr[first + 1];
        return std::find(first_begin, first_end, second) != first_end;
    };
#pragma omp parallel for reduction(+ : numTriangles)
    for (int first = 0; first < numVertices; first++) {
        for (int i = rowPtr[first]; i < rowPtr[first + 1]; i++) {
            for (int j = i + 1; j < rowPtr[first + 1]; j++) {
                const auto second = colIdx[i];
                const auto third  = colIdx[j];
                if (intersect(second, third)) {
                    numTriangles++;
                }
            }
        }
    }
    return numTriangles;
}
}  // namespace tot